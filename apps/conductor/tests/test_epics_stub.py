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

    This passes here and fails on a GitHub runner, and the reason is
    not known. It was first read as a slow search, because the test
    before this one clears the channel for this record and a fresh
    search is UDP. Widening the wait from 5s to 30s was tried and the
    runner sat out the whole 30 seconds, so the monitor is not arriving
    late there, it is not arriving. The bound is back at 5s because a
    longer one buys nothing and costs every run.

    What has not been ruled out is the thing worth ruling out first:
    pyepics caches a PV per name, and the clear above destroys that
    name's channel without evicting the cache, so a monitor taken out
    afterwards may be binding to a handle that is already gone. If that
    is what this is, it is not a test artefact. A conductor watches
    scan records with the same call, and clearing on reconnect is what
    the change that added this was for.
    """
    seen: list[object] = []

    def note(**arrived: object) -> None:
        seen.append(arrived.get("char_value"))

    assert epics.camonitor(_ioc.OTHER_MOTOR, callback=note) is None

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and not seen:
        time.sleep(0.05)
    assert seen, "a monitor was established and delivered nothing within 5s"

    assert epics.camonitor_clear(_ioc.OTHER_MOTOR) is None
