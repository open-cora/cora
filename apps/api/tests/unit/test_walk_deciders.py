"""The three decisions a walk's write side makes.

One file for three deciders rather than three, because two of them are
four lines and the third is the only one with anything to say. What it
has to say is the detail table: each outcome carries its own fields and
no others, which is the one rule here that a caller can get wrong in a
way the type system does not catch.

The refusal order in the step decider is pinned deliberately. A walk
that has ended is refused before its index is looked at, because a
caller told its index was out of range would go hunting an off-by-one
that is not there.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.procedure import MoveStep, Procedure, ProcedureName
from aroc.execution.aggregates.walk import (
    InvalidStepReportError,
    StepOutcome,
    Walk,
    WalkAlreadyEndedError,
    WalkAlreadyExistsError,
    WalkCannotBeClaimedError,
    WalkClaimed,
    WalkDispatched,
    WalkEnded,
    WalkNotFoundError,
    WalkStepAlreadyReportedError,
    WalkStepBroken,
    WalkStepDone,
    WalkStepOutOfRangeError,
    WalkStepRefused,
    WalkStepSkipped,
    evolve,
    fold,
)
from aroc.execution.features.claim_walk import ClaimWalk
from aroc.execution.features.claim_walk import decide as decide_claim
from aroc.execution.features.dispatch_walk import DispatchWalk, DispatchWalkContext
from aroc.execution.features.dispatch_walk import decide as decide_dispatch
from aroc.execution.features.end_walk import EndWalk
from aroc.execution.features.end_walk import decide as decide_end
from aroc.execution.features.report_step import ReportWalkStep
from aroc.execution.features.report_step import decide as decide_step

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
_ID = UUID(int=1)
_PROCEDURE_ID = UUID(int=7)
_STEPS = ("move 2bmb:m1 to 0.0", "acquire tomo_scan", "move 2bmb:m2 to 5.0")


def _live(*, ended: bool = False, reported: tuple[int, ...] = ()) -> Walk:
    events: list[object] = [
        WalkDispatched(
            walk_id=_ID,
            procedure_id=_PROCEDURE_ID,
            procedure_name="align_then_scan",
            steps=list(_STEPS),
            occurred_at=_NOW,
        )
    ]
    events.extend(WalkStepSkipped(walk_id=_ID, index=index, occurred_at=_NOW) for index in reported)
    if ended:
        events.append(WalkEnded(walk_id=_ID, occurred_at=_NOW))
    state = fold(events)  # pyright: ignore[reportArgumentType]
    assert state is not None
    return state


def _report(**overrides: object) -> ReportWalkStep:
    fields: dict[str, object] = {
        "walk_id": _ID,
        "index": 0,
        "outcome": StepOutcome.DONE,
    }
    fields.update(overrides)
    return ReportWalkStep(**fields)  # pyright: ignore[reportArgumentType]


def _procedure(*steps: object) -> DispatchWalkContext:
    composed = steps if steps else (MoveStep(record="2bmb:m1", to=0.0),)
    return DispatchWalkContext(
        procedure=Procedure(
            id=_PROCEDURE_ID,
            name=ProcedureName("align_then_scan"),
            steps=composed,  # pyright: ignore[reportArgumentType]
        )
    )


def test_dispatching_a_walk_on_an_empty_stream_emits_one_event() -> None:
    events = decide_dispatch(
        None,
        DispatchWalk(procedure_id=_PROCEDURE_ID),
        context=_procedure(MoveStep(record="2bmb:m1", to=0.0)),
        now=_NOW,
        new_id=_ID,
    )
    assert events == [
        WalkDispatched(
            walk_id=_ID,
            procedure_id=_PROCEDURE_ID,
            procedure_name="align_then_scan",
            steps=["move 2bmb:m1 to 0.0"],
            occurred_at=_NOW,
        )
    ]


def test_the_dispatched_walk_copies_the_procedures_steps_in_order() -> None:
    """The walk's own record has to be readable after the thing driving
    it has gone, so the steps are copied rather than only cited."""
    events = decide_dispatch(
        None,
        DispatchWalk(procedure_id=_PROCEDURE_ID),
        context=_procedure(
            MoveStep(record="2bmb:m1", to=0.0),
            MoveStep(record="2bmb:m2", to=5.0),
        ),
        now=_NOW,
        new_id=_ID,
    )
    assert events[0].steps == ["move 2bmb:m1 to 0.0", "move 2bmb:m2 to 5.0"]


def test_dispatching_a_walk_onto_a_live_stream_is_refused() -> None:
    with pytest.raises(WalkAlreadyExistsError):
        decide_dispatch(
            _live(),
            DispatchWalk(procedure_id=_PROCEDURE_ID),
            context=_procedure(),
            now=_NOW,
            new_id=_ID,
        )


def test_claiming_a_dispatched_walk_emits_one_event() -> None:
    events = decide_claim(_live(), ClaimWalk(walk_id=_ID), now=_NOW)
    assert events == [WalkClaimed(walk_id=_ID, occurred_at=_NOW)]


def test_claiming_a_walk_twice_is_refused() -> None:
    """Two drivers each believing they own one traversal. Nothing here
    can stop the second from moving a motor; refusing keeps the
    disagreement in the log rather than only at the beamline."""
    claimed = evolve(_live(), WalkClaimed(walk_id=_ID, occurred_at=_NOW))
    with pytest.raises(WalkCannotBeClaimedError):
        decide_claim(claimed, ClaimWalk(walk_id=_ID), now=_NOW)


def test_claiming_a_walk_that_was_never_dispatched_is_refused() -> None:
    with pytest.raises(WalkNotFoundError):
        decide_claim(None, ClaimWalk(walk_id=_ID), now=_NOW)


def test_claiming_a_walk_that_already_ended_is_refused() -> None:
    with pytest.raises(WalkCannotBeClaimedError):
        decide_claim(_live(ended=True), ClaimWalk(walk_id=_ID), now=_NOW)


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            _report(outcome=StepOutcome.DONE, engine_reference="uid-7"),
            WalkStepDone(walk_id=_ID, index=0, engine_reference="uid-7", occurred_at=_NOW),
        ),
        (
            _report(outcome=StepOutcome.DONE),
            WalkStepDone(walk_id=_ID, index=0, engine_reference=None, occurred_at=_NOW),
        ),
        (
            _report(outcome=StepOutcome.REFUSED),
            WalkStepRefused(walk_id=_ID, index=0, occurred_at=_NOW),
        ),
        (
            _report(outcome=StepOutcome.BROKEN, cause="TimeoutError"),
            WalkStepBroken(walk_id=_ID, index=0, cause="TimeoutError", occurred_at=_NOW),
        ),
        (
            _report(outcome=StepOutcome.SKIPPED),
            WalkStepSkipped(walk_id=_ID, index=0, occurred_at=_NOW),
        ),
    ],
    ids=["done with a run", "done with no run", "refused", "broken", "skipped"],
)
def test_each_outcome_produces_its_own_event(command: ReportWalkStep, expected: object) -> None:
    assert decide_step(_live(), command, now=_NOW) == [expected]


@pytest.mark.parametrize(
    ("command", "stray"),
    [
        (_report(outcome=StepOutcome.DONE, cause="TimeoutError"), "cause"),
        (_report(outcome=StepOutcome.SKIPPED, engine_reference="uid-7"), "engine_reference"),
        (_report(outcome=StepOutcome.REFUSED, cause="TimeoutError"), "cause"),
        (_report(outcome=StepOutcome.REFUSED, engine_reference="uid-7"), "engine_reference"),
    ],
    ids=["done with a cause", "skipped with a run", "refused with a cause", "refused with a run"],
)
def test_a_detail_from_another_outcome_is_refused(command: ReportWalkStep, stray: str) -> None:
    with pytest.raises(InvalidStepReportError, match=stray):
        decide_step(_live(), command, now=_NOW)


def test_a_break_that_does_not_name_what_was_raised_is_refused() -> None:
    with pytest.raises(InvalidStepReportError, match="raised"):
        decide_step(_live(), _report(outcome=StepOutcome.BROKEN), now=_NOW)


def test_reporting_a_step_of_a_walk_that_was_never_recorded_is_refused() -> None:
    with pytest.raises(WalkNotFoundError):
        decide_step(None, _report(), now=_NOW)


@pytest.mark.parametrize("index", [-1, 3, 99], ids=["before", "just past", "far past"])
def test_reporting_a_step_the_walk_does_not_have_is_refused(index: int) -> None:
    with pytest.raises(WalkStepOutOfRangeError):
        decide_step(_live(), _report(index=index), now=_NOW)


def test_reporting_a_step_twice_is_refused_rather_than_taken_as_a_correction() -> None:
    with pytest.raises(WalkStepAlreadyReportedError):
        decide_step(_live(reported=(1,)), _report(index=1), now=_NOW)


def test_steps_out_of_order_are_accepted() -> None:
    """A driver walks in order, so out-of-order arrival means retries raced."""
    events = decide_step(_live(), _report(index=2), now=_NOW)
    assert events == [WalkStepDone(walk_id=_ID, index=2, engine_reference=None, occurred_at=_NOW)]


def test_an_ended_walk_refuses_a_step_before_looking_at_its_index() -> None:
    """The closed walk is the useful fact; an index complaint would mislead."""
    with pytest.raises(WalkAlreadyEndedError):
        decide_step(_live(ended=True), _report(index=99), now=_NOW)


def test_ending_a_walk_that_reported_every_step_emits_one_event() -> None:
    assert decide_end(_live(reported=(0, 1, 2)), EndWalk(walk_id=_ID), now=_NOW) == [
        WalkEnded(walk_id=_ID, occurred_at=_NOW)
    ]


def test_ending_a_walk_whose_steps_are_unreported_is_allowed() -> None:
    """Otherwise the only walks that could be closed are the ones not needing it."""
    assert decide_end(_live(), EndWalk(walk_id=_ID), now=_NOW) == [
        WalkEnded(walk_id=_ID, occurred_at=_NOW)
    ]


def test_ending_a_walk_that_was_never_recorded_is_refused() -> None:
    with pytest.raises(WalkNotFoundError):
        decide_end(None, EndWalk(walk_id=uuid4()), now=_NOW)


def test_ending_a_walk_twice_is_refused() -> None:
    with pytest.raises(WalkAlreadyEndedError):
        decide_end(_live(ended=True), EndWalk(walk_id=_ID), now=_NOW)
