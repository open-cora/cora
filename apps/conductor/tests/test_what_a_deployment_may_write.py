"""A conductor writes where its deployment said it may, and nowhere else.

The refusal happens before anything is put, so every check here runs
against the real adapter with no IOC behind it. That is the point of
deciding first: a record outside the confinement never reaches Channel
Access, so there is nothing to connect to and nothing to clean up.
"""

from __future__ import annotations

import pytest

from conductor.adapters.epics_control import EpicsControl, OutsideConfinementError
from conductor.claims import Claim, Scope
from conductor.conduct import conduct
from conductor.outcomes import Broke, Done, Skipped
from conductor.procedure import RECORD_PARAMETER, SET_ROUTINE, VALUE_PARAMETER, Procedure, Step
from tests._fakes import RecordingRunning, repertoire_of

SIMULATED = "corasim19bm:"
REAL_MOTOR = "19bmSoft:aero:m1"


def confined_to(*names: str) -> EpicsControl:
    """The real control adapter, told what this deployment may write."""
    return EpicsControl(writable=frozenset(Scope.parse(name) for name in names))


def write(control: EpicsControl, record: str, value: float = 3.0) -> None:
    """Ask the adapter for the one routine it runs."""
    control.run(SET_ROUTINE, {RECORD_PARAMETER: record, VALUE_PARAMETER: value}, None)


def test_a_record_beneath_a_permitted_namespace_is_allowed() -> None:
    assert confined_to(SIMULATED).permits(f"{SIMULATED}m1")


def test_a_record_outside_every_scope_is_refused_before_anything_is_put() -> None:
    with pytest.raises(OutsideConfinementError):
        write(confined_to(SIMULATED), REAL_MOTOR)


def test_a_confinement_naming_nothing_refuses_every_record() -> None:
    with pytest.raises(OutsideConfinementError) as refusal:
        write(confined_to(), f"{SIMULATED}m1")

    assert "no writable scopes are configured" in str(refusal.value)


def test_a_refusal_against_a_configured_confinement_names_what_may_be_written() -> None:
    with pytest.raises(OutsideConfinementError) as refusal:
        write(confined_to(SIMULATED), REAL_MOTOR)

    assert SIMULATED in str(refusal.value)
    assert "no writable scopes" not in str(refusal.value)


def test_a_permitted_record_does_not_permit_the_one_whose_name_extends_it() -> None:
    """The reason a scope is not a string prefix: two motors, one a prefix of the other."""
    with pytest.raises(OutsideConfinementError):
        write(confined_to(f"{SIMULATED}m1"), f"{SIMULATED}m10")


def test_a_field_of_a_permitted_record_is_allowed() -> None:
    assert confined_to(f"{SIMULATED}m1").permits(f"{SIMULATED}m1.VAL")


def test_a_field_suffix_does_not_reach_a_record_outside_the_confinement() -> None:
    with pytest.raises(OutsideConfinementError):
        write(confined_to(SIMULATED), f"{REAL_MOTOR}.VAL")


def test_a_walk_stops_at_a_refused_write_and_skips_every_step_after_it() -> None:
    procedure = Procedure(
        name="two_sets",
        steps=(
            Step.setting(record=REAL_MOTOR, value=1.0),
            Step.setting(record=f"{SIMULATED}m1", value=2.0),
        ),
    )

    walk = conduct(procedure, running=repertoire_of(confined_to(SIMULATED), RecordingRunning()))

    assert isinstance(walk.outcomes[0], Broke)
    assert isinstance(walk.outcomes[1], Skipped)


def test_a_walk_keeps_the_steps_that_ran_before_a_write_was_refused() -> None:
    engine = RecordingRunning()
    procedure = Procedure(
        name="run_then_refused_set",
        steps=(
            Step(routine="tomo_scan", claim=Claim.over(f"{SIMULATED}m1")),
            Step.setting(record=REAL_MOTOR, value=1.0),
        ),
    )

    walk = conduct(procedure, running=repertoire_of(confined_to(SIMULATED), engine))

    assert isinstance(walk.outcomes[0], Done)
    assert isinstance(walk.outcomes[1], Broke)
    assert [routine for routine, _, _ in engine.asked] == ["tomo_scan"]


def test_a_walk_naming_the_refusal_says_which_record_was_not_written() -> None:
    procedure = Procedure(
        name="one_set",
        steps=(Step.setting(record=REAL_MOTOR, value=1.0),),
    )

    walk = conduct(procedure, running=repertoire_of(confined_to(SIMULATED), RecordingRunning()))

    broke = walk.outcomes[0]
    assert isinstance(broke, Broke)
    assert REAL_MOTOR in broke.cause
