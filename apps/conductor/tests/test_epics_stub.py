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

import threading
import time
import uuid
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
    assert isinstance(float(connected.get(count=1, timeout=5.0)), float)

    # What a setting is checked against before the TomoScan engine writes
    # it: the record's type and size, and the limits it publishes.
    assert isinstance(connected.type, str)
    assert connected.count == 1
    assert connected.nelm == 1
    published = connected.get_ctrlvars(timeout=5.0)
    assert isinstance(published, dict)
    assert {"lower_ctrl_limit", "upper_ctrl_limit"} <= set(published)

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

    `camonitor` attaches its callback only after the channel has connected
    and been read, and pyepics does not run it for the value the channel
    already holds. So the value a subscription starts with reaches the
    callback only when it happens to arrive after the callback is attached.
    That is a race, and waiting longer cannot win one already lost: this
    waited 5s and then 30s for that first value, and failed both ways on
    shared runners. What makes delivery certain is a change after
    subscribing, so the record's description is written. That moves
    nothing: what a motor does when it is driven belongs to
    `test_epics_control.py`, and nothing here reads a position.

    The callback takes keywords only. pyepics chooses which ones to pass
    from what the channel carries, which is why the stub types it
    loosely and why this takes them as a mapping rather than by name.

    The connection is made before the monitor and asserted separately,
    which is not ceremony. `camonitor` connects first and subscribes
    only `if thispv.connected`, giving up after its own
    `connection_timeout` of 5s by default. On a miss it registers
    nothing and returns `None` exactly as it does on success. A search is
    UDP and answered when it is answered, which is milliseconds against a
    loopback IOC and was more than 5s on a shared runner, so the bound
    handed to `camonitor` is 30s and connecting first means a failure
    says which half broke.
    """
    described = f"{_ioc.OTHER_MOTOR}.DESC"
    written = f"monitored {uuid.uuid4().hex[:8]}"
    seen: list[object] = []

    def note(**arrived: object) -> None:
        seen.append(arrived.get("char_value"))

    channel = epics.PV(described, connection_timeout=30.0)
    assert channel.wait_for_connection(timeout=30.0) is True, (
        "the record never connected, so no monitor could have been established"
    )

    assert epics.camonitor(described, callback=note, connection_timeout=30.0) is None
    assert epics.caput(described, written, wait=True, timeout=30.0) == 1

    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline and written not in seen:
        time.sleep(0.05)
    assert written in seen, "a monitor was established and did not deliver a later write"

    assert epics.camonitor_clear(described) is None


def test_a_channel_given_a_callback_hears_its_record_and_is_accepted_for_clearing() -> None:
    """The pair a test holds a channel at its first update with.

    A channel subscribes for itself as it connects, and that subscription
    delivers what the record already holds, so nothing has to move for
    the callback to run. The bounds are the generous ones above, for the
    reason given there.
    """
    heard = threading.Event()

    def hear(**_: object) -> None:
        heard.set()

    channel = epics.PV(_ioc.OTHER_MOTOR, callback=hear, connection_timeout=30.0)
    assert channel.wait_for_connection(timeout=30.0) is True
    assert heard.wait(timeout=5.0), "the channel connected and its callback heard nothing in 5s"

    assert channel.clear_auto_monitor() is None
