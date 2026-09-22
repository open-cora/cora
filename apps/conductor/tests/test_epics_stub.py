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

    assert epics.caput(_ioc.OTHER_MOTOR, 0.0, wait=True, timeout=30.0) == 1
    assert isinstance(float(epics.caget(_ioc.OTHER_MOTOR, timeout=5.0)), float)
    assert isinstance(epics.caget(f"{_ioc.MOTOR}.SPMG", as_string=True, timeout=5.0), str)


def test_a_pv_that_never_connects_reports_it_rather_than_raising() -> None:
    """The behaviour `EpicsControl._connect` turns into its own refusal."""
    missing = epics.PV(_ioc.ABSENT, connection_timeout=0.5)
    assert missing.wait_for_connection(timeout=0.5) is False
