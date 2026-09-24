"""The Walk aggregate: its six events, its fold, and the round trip.

The first aggregate here whose state holds a collection rather than a
handful of scalars, so the properties worth pinning are about that: the
step list is fixed at the genesis and never grows, each step event
touches exactly one element, and nothing about the walk itself moves
when a step does.

The round trip matters for the same reason it does next door. The
genesis re-validates three things on the way back out of the log, so a
payload that could not be written today has to fail on read rather than
become state nothing checked.
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.walk import (
    InvalidWalkProcedureNameError,
    InvalidWalkStepsError,
    StepOutcome,
    Walk,
    WalkEnded,
    WalkEvent,
    WalkReported,
    WalkStepBroken,
    WalkStepDone,
    WalkStepRefused,
    WalkStepSkipped,
    evolve,
    fold,
    from_stored,
    to_payload,
    validated_steps,
)
from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.shared.identifier import Identifier, InvalidIdentifierError

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
_REF = Identifier(scheme="conductor", value="walk-1")
_STEPS = ["move 2bmb:m1 to 0.0", "acquire tomo_scan", "move 2bmb:m2 to 5.0"]


def _reported(**overrides: object) -> WalkReported:
    fields: dict[str, object] = {
        "walk_id": uuid4(),
        "reference_scheme": _REF.scheme,
        "reference_value": _REF.value,
        "procedure_name": "align_then_scan",
        "steps": list(_STEPS),
        "occurred_at": _WHEN,
    }
    fields.update(overrides)
    return WalkReported(**fields)  # pyright: ignore[reportArgumentType]


def _stored(event: WalkEvent) -> StoredEvent:
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type="Walk",
        stream_id=event.walk_id,
        version=1,
        event_type=type(event).__name__,
        schema_version=1,
        payload=to_payload(event),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=event.occurred_at,
        recorded_at=event.occurred_at,
    )


def _walk(*events: WalkEvent) -> Walk:
    state = fold([_reported(walk_id=UUID(int=1)), *events])
    assert state is not None
    return state


def test_the_genesis_builds_a_step_for_every_step_it_names() -> None:
    state = _walk()
    assert state.step_count == 3
    assert [step.describes for step in state.steps] == _STEPS
    assert state.reported_count == 0
    assert not state.ended


def test_a_walk_with_no_events_folds_to_none() -> None:
    assert fold([]) is None


def test_reporting_a_step_done_leaves_every_other_step_alone() -> None:
    state = _walk(
        WalkStepDone(walk_id=UUID(int=1), index=1, engine_reference="uid-7", occurred_at=_WHEN)
    )
    assert state.steps[1].outcome is StepOutcome.DONE
    assert state.steps[1].engine_reference == "uid-7"
    assert [step.outcome for step in state.steps] == [None, StepOutcome.DONE, None]
    assert state.reported_count == 1


def test_a_done_step_that_opened_no_run_carries_no_reference() -> None:
    """A move drives a motor and opens nothing, which is most steps."""
    state = _walk(
        WalkStepDone(walk_id=UUID(int=1), index=0, engine_reference=None, occurred_at=_WHEN)
    )
    assert state.steps[0].outcome is StepOutcome.DONE
    assert state.steps[0].engine_reference is None


def test_a_refused_step_records_the_outcome_and_no_detail() -> None:
    state = _walk(WalkStepRefused(walk_id=UUID(int=1), index=0, occurred_at=_WHEN))
    step = state.steps[0]
    assert step.outcome is StepOutcome.REFUSED
    assert (step.engine_reference, step.cause) == (None, None)


def test_a_broken_step_keeps_the_class_that_was_raised() -> None:
    state = _walk(
        WalkStepBroken(walk_id=UUID(int=1), index=1, cause="TimeoutError", occurred_at=_WHEN)
    )
    assert state.steps[1].outcome is StepOutcome.BROKEN
    assert state.steps[1].cause == "TimeoutError"


def test_a_skipped_step_carries_nothing_beyond_the_outcome() -> None:
    state = _walk(WalkStepSkipped(walk_id=UUID(int=1), index=2, occurred_at=_WHEN))
    step = state.steps[2]
    assert step.outcome is StepOutcome.SKIPPED
    assert (step.engine_reference, step.cause) == (None, None)


def test_ending_a_walk_moves_nothing_but_the_ending() -> None:
    before = _walk(
        WalkStepDone(walk_id=UUID(int=1), index=0, engine_reference=None, occurred_at=_WHEN)
    )
    after = evolve(before, WalkEnded(walk_id=UUID(int=1), occurred_at=_WHEN))
    assert after.ended
    assert after.steps == before.steps
    assert (after.reference, after.procedure_name) == (before.reference, before.procedure_name)


def test_a_walk_can_end_with_steps_still_unreported() -> None:
    """What a record left behind by a driver that died looks like."""
    state = _walk(
        WalkStepDone(walk_id=UUID(int=1), index=0, engine_reference=None, occurred_at=_WHEN),
        WalkEnded(walk_id=UUID(int=1), occurred_at=_WHEN),
    )
    assert state.ended
    assert (state.reported_count, state.step_count) == (1, 3)


@pytest.mark.parametrize(
    "event",
    [
        _reported(walk_id=UUID(int=1)),
        WalkStepDone(walk_id=UUID(int=1), index=0, engine_reference="uid-7", occurred_at=_WHEN),
        WalkStepDone(walk_id=UUID(int=1), index=0, engine_reference=None, occurred_at=_WHEN),
        WalkStepRefused(walk_id=UUID(int=1), index=0, occurred_at=_WHEN),
        WalkStepBroken(walk_id=UUID(int=1), index=0, cause="TimeoutError", occurred_at=_WHEN),
        WalkStepSkipped(walk_id=UUID(int=1), index=0, occurred_at=_WHEN),
        WalkEnded(walk_id=UUID(int=1), occurred_at=_WHEN),
    ],
    ids=lambda event: type(event).__name__,
)
def test_every_event_survives_a_round_trip_through_the_store(event: WalkEvent) -> None:
    assert from_stored(_stored(event)) == event


def test_an_unknown_event_type_is_refused_rather_than_guessed_at() -> None:
    stored = replace(_stored(_reported()), event_type="WalkWandered")
    with pytest.raises(ValueError, match="Unknown Walk event_type"):
        from_stored(stored)


def test_a_stored_genesis_whose_reference_no_longer_passes_fails_on_read() -> None:
    with pytest.raises(InvalidIdentifierError):
        fold([_reported(reference_value="")])


def test_a_stored_genesis_whose_name_no_longer_passes_fails_on_read() -> None:
    with pytest.raises(InvalidWalkProcedureNameError):
        fold([_reported(procedure_name="   ")])


def test_a_stored_genesis_whose_steps_no_longer_pass_fails_on_read() -> None:
    with pytest.raises(InvalidWalkStepsError):
        fold([_reported(steps=[])])


def test_a_step_event_on_an_empty_stream_says_the_log_is_out_of_order() -> None:
    with pytest.raises(ValueError, match="WalkStepDone"):
        evolve(
            None, WalkStepDone(walk_id=uuid4(), index=0, engine_reference=None, occurred_at=_WHEN)
        )


def test_steps_are_trimmed_on_the_way_in() -> None:
    assert validated_steps(("  move m1  ",)) == ("move m1",)


def test_a_step_list_with_a_blank_entry_is_refused() -> None:
    with pytest.raises(InvalidWalkStepsError, match="Step 1"):
        validated_steps(("move m1", "   "))


def test_a_step_list_past_the_bound_is_refused() -> None:
    with pytest.raises(InvalidWalkStepsError, match="at most"):
        validated_steps(tuple(f"move m{n}" for n in range(1001)))


def test_a_step_longer_than_the_bound_is_refused() -> None:
    with pytest.raises(InvalidWalkStepsError, match="the bound is"):
        validated_steps(("x" * 501,))
