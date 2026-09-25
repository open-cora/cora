"""The control adapter against a real motor record, over a real CA socket.

Every test here is the adapter's side of something a spike measured: a
motor failing to arrive while every layer reported success. These check
that this layer does not.
"""

from __future__ import annotations

import threading
import time

import epics
import pytest

from conductor.adapters.epics_control import (
    DEADBAND_FIELD,
    DONE_MOVING_FIELD,
    DeviceHeldError,
    DidNotArriveError,
    EpicsControl,
    StillMovingError,
    UnreachableRecordError,
    records_of,
)
from tests import _ioc

pytestmark = [pytest.mark.channel_access, pytest.mark.usefixtures("motor_at_home")]

TRAVEL = 3.0
"""How far the two paired tests below move. Three seconds at velocity 1.0."""

SETTLE = 6.0
"""Long enough for an undisturbed move of `TRAVEL` and short enough to bound the suite."""


def test_move_to_a_reachable_motor_arrives() -> None:
    with EpicsControl() as control:
        control.move(_ioc.MOTOR, 2.0)
        assert control.read(_ioc.MOTOR) == pytest.approx(2.0, abs=0.01)


def test_move_is_verified_against_the_readback_field() -> None:
    """Not against `.VAL`, which only says what the caller wrote."""
    with EpicsControl() as control:
        control.move(_ioc.MOTOR, 1.0)
        checked = control.verified[-1]
        assert checked.readback
        assert checked.against == f"{_ioc.MOTOR}.RBV"


def test_move_records_what_it_asked_and_what_it_got() -> None:
    with EpicsControl() as control:
        control.move(_ioc.MOTOR, 3.0)
        checked = control.verified[-1]
        assert checked.asked == 3.0
        assert checked.got == pytest.approx(3.0, abs=0.01)


def test_move_on_a_held_motor_is_refused_before_it_writes() -> None:
    """The `rival_hold` finding: a held motor accepts every move and makes none."""
    epics.caput(f"{_ioc.MOTOR}.SPMG", "Stop", wait=True, timeout=10)
    time.sleep(0.5)
    with EpicsControl() as control, pytest.raises(DeviceHeldError) as refused:
        control.move(_ioc.MOTOR, 4.0)
    assert refused.value.record == _ioc.MOTOR
    assert refused.value.holding == "Stop"


def test_move_on_a_held_motor_leaves_it_where_it_was() -> None:
    """The setup uses the adapter rather than a put, and that is not incidental.

    Written with `epics.caput(..., wait=True)` to place the motor, this
    test failed at 0.5556: the put returned while the motor was still
    travelling, and the hold froze it partway. A bare put cannot be
    trusted to have arrived even in a test fixture, which is the whole
    reason the adapter under test does more than put.
    """
    with EpicsControl() as control:
        control.move(_ioc.MOTOR, 1.0)
        epics.caput(f"{_ioc.MOTOR}.SPMG", "Stop", wait=True, timeout=10)
        time.sleep(0.5)
        with pytest.raises(DeviceHeldError):
            control.move(_ioc.MOTOR, 8.0)
        assert epics.caget(f"{_ioc.MOTOR}.RBV") == pytest.approx(1.0, abs=0.05)


def test_move_undisturbed_arrives_within_the_same_settle() -> None:
    """The control for the test below, so its failure cannot be a short settle."""
    with EpicsControl(settle=SETTLE) as control:
        control.move(_ioc.MOTOR, TRAVEL)
        assert control.verified[-1].got == pytest.approx(TRAVEL, abs=0.01)


def test_move_a_rival_redirects_mid_flight_does_not_claim_arrival() -> None:
    """The `rival_move` finding, which a bare put reports as success.

    The rival writes while the move is in flight, which is the order that
    matters: a rival writing first is simply overwritten by the adapter
    and nothing goes wrong. Here the motor sails past the target it was
    sent to and keeps going, and the adapter says so instead of
    returning.
    """
    rival = threading.Timer(
        0.8, epics.caput, args=(f"{_ioc.MOTOR}.VAL", 9.0), kwargs={"wait": False}
    )
    with EpicsControl(settle=SETTLE) as control:
        rival.start()
        try:
            with pytest.raises(DidNotArriveError) as missed:
                control.move(_ioc.MOTOR, TRAVEL)
        finally:
            rival.cancel()

    assert missed.value.asked == TRAVEL
    assert missed.value.got > TRAVEL, "the rival should have carried it past the target"


def test_move_that_arrives_confirms_the_motion_stopped() -> None:
    """Position alone let the `rival_move` case through, so arrival is two checks."""
    with EpicsControl() as control:
        control.move(_ioc.MOTOR, 2.0)
        assert control.verified[-1].settled
        assert epics.caget(f"{_ioc.MOTOR}.{DONE_MOVING_FIELD}") == 1


def test_move_inside_a_wide_deadband_but_still_travelling_is_not_called_arrival() -> None:
    """The half of the defect a position check cannot see, isolated.

    A deadband of nine on a ten unit move makes the motor count as close
    enough from one unit in, so every poll after that agrees on position
    while the motor is still crossing the room. Only `.DMOV` separates
    the two, which is why this raises rather than returning.
    """
    epics.caput(f"{_ioc.MOTOR}.{DEADBAND_FIELD}", 9.0, wait=True, timeout=10)
    time.sleep(0.2)
    with EpicsControl(settle=3.0) as control, pytest.raises(StillMovingError) as moving:
        control.move(_ioc.MOTOR, 10.0)

    assert moving.value.asked == 10.0
    assert abs(moving.value.got - 10.0) <= 9.0, "the point is that position agreed"
    assert moving.value.got < 5.0, "and that the motor was nowhere near its target"


def test_move_to_a_record_with_no_motion_field_records_the_weaker_check() -> None:
    """A setpoint is not a motor, and `Verified` says which one it got.

    The deadband field stands in for one: it takes a number, serves
    neither `.RBV` nor `.DMOV` of its own, and the fixture puts it back.
    """
    setpoint = f"{_ioc.MOTOR}.{DEADBAND_FIELD}"
    with EpicsControl() as control:
        control.move(setpoint, 0.25)
        checked = control.verified[-1]

    assert checked.settled is False
    assert checked.readback is False
    assert checked.against == setpoint


def test_move_to_a_record_nothing_serves_is_refused() -> None:
    with EpicsControl(connect_timeout=0.5) as control, pytest.raises(UnreachableRecordError):
        control.move(_ioc.ABSENT, 1.0)


def test_read_of_a_record_nothing_serves_is_refused() -> None:
    with EpicsControl(connect_timeout=0.5) as control, pytest.raises(UnreachableRecordError):
        control.read(_ioc.ABSENT)


def test_trouble_on_one_motor_leaves_another_movable() -> None:
    """Device-scoped, the way the `other_device` scenario was."""
    epics.caput(f"{_ioc.MOTOR}.SPMG", "Stop", wait=True, timeout=10)
    time.sleep(0.5)
    with EpicsControl() as control:
        with pytest.raises(DeviceHeldError):
            control.move(_ioc.MOTOR, 5.0)
        control.move(_ioc.OTHER_MOTOR, 2.0)
        assert control.read(_ioc.OTHER_MOTOR) == pytest.approx(2.0, abs=0.01)


def test_every_verified_move_is_kept_in_order() -> None:
    with EpicsControl() as control:
        control.move(_ioc.MOTOR, 1.0)
        control.move(_ioc.MOTOR, 2.0)
        assert [checked.asked for checked in control.verified] == [1.0, 2.0]


def test_records_of_drops_a_field_suffix() -> None:
    assert list(records_of("2bmb:m1.VAL", "2bmb:m2")) == ["2bmb:m1", "2bmb:m2"]
