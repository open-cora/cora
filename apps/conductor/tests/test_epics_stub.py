"""Check the hand-written pyepics stub against the package it stands in for.

`typings/epics/__init__.pyi` is taken on trust by pyright and checked by
nothing else, so a pyepics release that moved a signature would teach the
type checker something untrue and no run would go red. This is what makes
one go red: every name the stub declares is exercised against the live
soft IOC and asserted to behave the way the stub says.

It is deliberately about shape rather than about motors. What a motor does
when it is moved is `test_epics_control.py`'s subject.

That distinction is load-bearing and was got wrong first time. This asserted
the motor had reached where it was put, which passed alone and failed in the
suite once a sibling test left the second motor somewhere else: a bare put
returns while the motor is still travelling, so the read landed mid-flight.
Asserting arrival after a put is the mistake the adapter under test exists to
prevent, and it has no business here either. Nothing below reads a position.
"""

from __future__ import annotations

import time
from ctypes import c_long

import epics
import pytest

from tests import _ioc

pytestmark = [pytest.mark.channel_access, pytest.mark.usefixtures("motor_at_home")]


def test_the_epics_stub_describes_the_package_it_stands_in_for() -> None:
    connected = epics.PV(_ioc.OTHER_MOTOR, connection_timeout=2.0)
    assert connected.wait_for_connection(timeout=5.0) is True
    assert connected.pvname == _ioc.OTHER_MOTOR

    # `put` returns 1 on success, which is why the adapter tests for None
    # rather than for falsehood.
    assert connected.put(1.0, wait=True, timeout=30.0) == 1

    assert isinstance(float(connected.get(timeout=5.0)), float)
    assert isinstance(connected.get(as_string=True, timeout=5.0), str)

    connected.disconnect()

    # `chid` is the library's handle, and `disconnect` above left it in
    # place. Clearing it is what lets a later channel for the same name
    # search afresh rather than inherit a widened retry interval.
    assert isinstance(connected.chid, c_long)
    assert isinstance(epics.ca.clear_channel(connected.chid), int)

    assert epics.caput(_ioc.OTHER_MOTOR, 0.0, wait=True, timeout=30.0) == 1
    assert isinstance(float(epics.caget(_ioc.OTHER_MOTOR, timeout=5.0)), float)
    assert isinstance(epics.caget(f"{_ioc.MOTOR}.SPMG", as_string=True, timeout=5.0), str)


def test_a_pv_that_never_connects_reports_it_rather_than_raising() -> None:
    """The behaviour `EpicsControl._connect` turns into its own refusal."""
    missing = epics.PV(_ioc.ABSENT, connection_timeout=0.5)
    assert missing.wait_for_connection(timeout=0.5) is False

    # The handle is made with the channel rather than with the connection,
    # so one this unresolved can still be cleared.
    assert isinstance(missing.chid, c_long)


def test_a_monitor_delivers_a_value_and_is_accepted_for_clearing() -> None:
    """The pair a scan's record ordering is watched with.

    A subscription delivers what the channel already holds as it is
    established, so nothing has to move for this to see something. That
    is the whole reason it can live in this file: what a motor does when
    it is driven belongs to `test_epics_control.py`, and nothing here
    reads a position.

    The callback takes keywords only. pyepics chooses which ones to pass
    from what the channel carries, which is why the stub types it
    loosely and why this takes them as a mapping rather than by name.

    The connection is made before the monitor and asserted separately,
    which is not ceremony. `camonitor` connects first and subscribes
    only `if thispv.connected`, giving up after its own
    `connection_timeout` of 5s by default. On a miss it registers
    nothing, returns `None` exactly as it does on success, and leaves
    a caller waiting on a subscription that was never taken out. No
    deadline below can rescue that, which is how this was found: the
    wait was widened from 5s to 30s and a runner sat out all 30.

    The connection here is a fresh CA search, because the test before
    this one clears this record's channel, and a search is UDP and
    answered when it is answered. That is milliseconds against a
    loopback IOC and was more than 5s on a shared runner. So the bound
    that matters is the one handed to `camonitor`, and the point of
    connecting first is that a failure now says which half broke.
    """
    seen: list[object] = []

    def note(**arrived: object) -> None:
        seen.append(arrived.get("char_value"))

    channel = epics.PV(_ioc.OTHER_MOTOR, connection_timeout=30.0)
    assert channel.wait_for_connection(timeout=30.0) is True, (
        "the record never connected, so no monitor could have been established"
    )

    assert epics.camonitor(_ioc.OTHER_MOTOR, callback=note, connection_timeout=30.0) is None

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not seen:
        time.sleep(0.05)
    assert seen, "a monitor was established and delivered nothing within 5s"

    assert epics.camonitor_clear(_ioc.OTHER_MOTOR) is None
