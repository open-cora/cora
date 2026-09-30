"""A conductor writes where its deployment said it may, and nowhere else."""

from __future__ import annotations

import pytest

from conductor.conduct import conduct
from conductor.confinement import Confinement, OutsideConfinementError
from conductor.outcomes import Broke, Done, Skipped
from conductor.procedure import Procedure, Set
from tests._fakes import RecordingAdjusting, RecordingRunning

SIMULATED = "corasim19bm:"
REAL_MOTOR = "19bmSoft:aero:m1"


def test_a_record_beneath_a_permitted_namespace_is_written_through() -> None:
    inner = RecordingAdjusting()
    confined = Confinement.around(inner, SIMULATED)

    confined.set(f"{SIMULATED}m1", 3.0)

    assert inner.moves == [(f"{SIMULATED}m1", 3.0)]


def test_a_record_outside_every_scope_never_reaches_the_seam_beneath() -> None:
    inner = RecordingAdjusting()
    confined = Confinement.around(inner, SIMULATED)

    with pytest.raises(OutsideConfinementError):
        confined.set(REAL_MOTOR, 3.0)

    assert inner.moves == []


def test_a_confinement_naming_nothing_refuses_every_record() -> None:
    inner = RecordingAdjusting()
    confined = Confinement.around(inner)

    with pytest.raises(OutsideConfinementError) as refusal:
        confined.set(f"{SIMULATED}m1", 3.0)

    assert inner.moves == []
    assert "no writable scopes are configured" in str(refusal.value)


def test_a_refusal_against_a_configured_confinement_names_what_may_be_written() -> None:
    confined = Confinement.around(RecordingAdjusting(), SIMULATED)

    with pytest.raises(OutsideConfinementError) as refusal:
        confined.set(REAL_MOTOR, 3.0)

    assert SIMULATED in str(refusal.value)
    assert "no writable scopes" not in str(refusal.value)


def test_a_permitted_record_does_not_permit_the_one_whose_name_extends_it() -> None:
    """The reason a scope is not a string prefix: two motors, one a prefix of the other."""
    inner = RecordingAdjusting()
    confined = Confinement.around(inner, f"{SIMULATED}m1")

    with pytest.raises(OutsideConfinementError):
        confined.set(f"{SIMULATED}m10", 3.0)

    assert inner.moves == []


def test_a_field_of_a_permitted_record_is_written_through() -> None:
    inner = RecordingAdjusting()
    confined = Confinement.around(inner, f"{SIMULATED}m1")

    confined.set(f"{SIMULATED}m1.VAL", 3.0)

    assert inner.moves == [(f"{SIMULATED}m1.VAL", 3.0)]


def test_a_field_suffix_does_not_reach_a_record_outside_the_confinement() -> None:
    inner = RecordingAdjusting()
    confined = Confinement.around(inner, SIMULATED)

    with pytest.raises(OutsideConfinementError):
        confined.set(f"{REAL_MOTOR}.VAL", 3.0)

    assert inner.moves == []


def test_a_walk_stops_at_a_refused_write_and_skips_every_step_after_it() -> None:
    inner = RecordingAdjusting()
    procedure = Procedure(
        name="two_sets",
        steps=(
            Set(record=REAL_MOTOR, to=1.0),
            Set(record=f"{SIMULATED}m1", to=2.0),
        ),
    )

    walk = conduct(
        procedure,
        adjusting=Confinement.around(inner, SIMULATED),
        running=RecordingRunning(),
    )

    assert isinstance(walk.outcomes[0], Broke)
    assert isinstance(walk.outcomes[1], Skipped)
    assert inner.moves == []


def test_a_walk_keeps_the_steps_that_ran_before_a_write_was_refused() -> None:
    inner = RecordingAdjusting()
    procedure = Procedure(
        name="permitted_then_not",
        steps=(
            Set(record=f"{SIMULATED}m1", to=2.0),
            Set(record=REAL_MOTOR, to=1.0),
        ),
    )

    walk = conduct(
        procedure,
        adjusting=Confinement.around(inner, SIMULATED),
        running=RecordingRunning(),
    )

    assert isinstance(walk.outcomes[0], Done)
    assert isinstance(walk.outcomes[1], Broke)
    assert inner.moves == [(f"{SIMULATED}m1", 2.0)]


def test_a_walk_naming_the_refusal_says_which_record_was_not_written() -> None:
    procedure = Procedure(
        name="one_set",
        steps=(Set(record=REAL_MOTOR, to=1.0),),
    )

    walk = conduct(
        procedure,
        adjusting=Confinement.around(RecordingAdjusting(), SIMULATED),
        running=RecordingRunning(),
    )

    broke = walk.outcomes[0]
    assert isinstance(broke, Broke)
    assert REAL_MOTOR in broke.cause
