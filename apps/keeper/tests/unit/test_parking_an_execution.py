"""A walk that stops at work still running elsewhere parks, and is taken back once it stops.

Four deciders and the fold meet here, because parking is one behaviour
spread across them: the park decider says when a walk may stop and wait,
the fold says when the wait is over, the claim decider lets a driver take
the walk back, and the step decider refuses a driver that walks on
without doing so.

The fold is pinned hardest. Ready is derived rather than reported, so the
only thing standing between a parked walk and a driver walking past a
transfer still moving is the rule that an ending counts only when it is
about the step the walk parked at.
"""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from keeper.execution.aggregates.execution import (
    DispatchedStep,
    Execution,
    ExecutionAlreadyEndedError,
    ExecutionCannotBeClaimedError,
    ExecutionCannotBeParkedError,
    ExecutionClaimed,
    ExecutionDispatched,
    ExecutionEnded,
    ExecutionEvent,
    ExecutionNotFoundError,
    ExecutionParked,
    ExecutionStatus,
    ExecutionStepBroken,
    ExecutionStepCannotBeReportedError,
    ExecutionStepDone,
    ExecutionStepEngineAborted,
    ExecutionStepEngineCompleted,
    ExecutionStepEngineFailed,
    ExecutionStepEngineStarted,
    ExecutionStepHandedOff,
    ExecutionStepRefused,
    ExecutionStepSkipped,
    StepOutcome,
    fold,
)
from keeper.execution.features.claim_execution import ClaimExecution
from keeper.execution.features.claim_execution import decide as decide_claim
from keeper.execution.features.end_execution import EndExecution
from keeper.execution.features.end_execution import decide as decide_end
from keeper.execution.features.park_execution import ParkExecution
from keeper.execution.features.park_execution import decide as decide_park
from keeper.execution.features.report_step import ReportExecutionStep
from keeper.execution.features.report_step import decide as decide_step

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 27, 9, 30, tzinfo=UTC)
_ID = UUID(int=1)
_STEP_IDS = (UUID(int=11), UUID(int=12), UUID(int=13))
_FIRST, _SECOND, _THIRD = _STEP_IDS


def _walk(*after: ExecutionEvent) -> Execution:
    """Fold a three-step execution: collect, move, process, then whatever follows."""
    state = fold(
        [
            ExecutionDispatched(
                execution_id=_ID,
                procedure_id=UUID(int=7),
                procedure_name="collect_then_move",
                beamline="2-bm",
                steps=[
                    DispatchedStep(id=step_id, describes=text, procedure_step_id=UUID(int=20 + n))
                    for n, (step_id, text) in enumerate(
                        zip(_STEP_IDS, ("run collect", "run move", "run process"), strict=True)
                    )
                ],
                routines=["collect", "move", "process"],
                occurred_at=_NOW,
            ),
            *after,
        ]
    )
    assert state is not None
    return state


def _done(index: int) -> ExecutionStepDone:
    return ExecutionStepDone(execution_id=_ID, index=index, engine_reference=None, occurred_at=_NOW)


def _handed_off(index: int) -> ExecutionStepHandedOff:
    return ExecutionStepHandedOff(
        execution_id=_ID, index=index, engine_reference=f"task-{index}", occurred_at=_NOW
    )


def _claimed() -> ExecutionClaimed:
    return ExecutionClaimed(execution_id=_ID, occurred_at=_NOW)


def _parked() -> ExecutionParked:
    return ExecutionParked(execution_id=_ID, occurred_at=_NOW)


def _started(step_id: UUID) -> ExecutionStepEngineStarted:
    return ExecutionStepEngineStarted(
        execution_id=_ID, step_id=step_id, engine_reference="task", occurred_at=_NOW
    )


def _completed(step_id: UUID) -> ExecutionStepEngineCompleted:
    return ExecutionStepEngineCompleted(execution_id=_ID, step_id=step_id, occurred_at=_NOW)


_PARKED_AT_THE_MOVE = (_claimed(), _done(0), _handed_off(1), _parked())
"""The walk every test below starts from: collected, handed the move off, parked."""


def test_parking_a_walk_whose_last_reported_step_was_handed_off_emits_one_event() -> None:
    state = _walk(_claimed(), _done(0), _handed_off(1))
    assert decide_park(state, ParkExecution(execution_id=_ID), now=_NOW) == [
        ExecutionParked(execution_id=_ID, occurred_at=_NOW)
    ]


def test_parking_a_walk_whose_handed_off_work_already_stopped_is_allowed() -> None:
    """The watcher can land between the driver's report of the handoff and its
    parking, and the driver could not have known."""
    state = _walk(_claimed(), _done(0), _handed_off(1), _started(_SECOND), _completed(_SECOND))
    assert decide_park(state, ParkExecution(execution_id=_ID), now=_NOW) == [
        ExecutionParked(execution_id=_ID, occurred_at=_NOW)
    ]


def test_parking_a_walk_that_hands_off_its_last_step_is_allowed() -> None:
    """It stays open until the last of its work has stopped, rather than
    reading as finished while that work is still running."""
    state = _walk(_claimed(), _done(0), _done(1), _handed_off(2))
    assert decide_park(state, ParkExecution(execution_id=_ID), now=_NOW) == [
        ExecutionParked(execution_id=_ID, occurred_at=_NOW)
    ]


def test_parking_a_walk_that_was_never_dispatched_is_refused() -> None:
    with pytest.raises(ExecutionNotFoundError):
        decide_park(None, ParkExecution(execution_id=_ID), now=_NOW)


def test_parking_a_walk_that_ended_is_refused_as_ended() -> None:
    state = _walk(_claimed(), _handed_off(0), ExecutionEnded(execution_id=_ID, occurred_at=_NOW))
    with pytest.raises(ExecutionAlreadyEndedError):
        decide_park(state, ParkExecution(execution_id=_ID), now=_NOW)


@pytest.mark.parametrize(
    ("after", "status"),
    [
        (_PARKED_AT_THE_MOVE, ExecutionStatus.PARKED),
        ((*_PARKED_AT_THE_MOVE, _completed(_SECOND)), ExecutionStatus.READY),
    ],
    ids=["parked", "ready"],
)
def test_parking_a_walk_a_second_time_is_refused(
    after: tuple[ExecutionEvent, ...], status: ExecutionStatus
) -> None:
    with pytest.raises(ExecutionCannotBeParkedError) as refused:
        decide_park(_walk(*after), ParkExecution(execution_id=_ID), now=_NOW)
    assert refused.value.status is status


def test_parking_a_walk_that_reported_nothing_is_refused() -> None:
    """Parked on nothing, it would wait for good: no report could release it."""
    with pytest.raises(ExecutionCannotBeParkedError, match="no step has been reported") as refused:
        decide_park(_walk(_claimed()), ParkExecution(execution_id=_ID), now=_NOW)
    assert refused.value.last is None


@pytest.mark.parametrize(
    ("last", "outcome"),
    [
        (_done(1), StepOutcome.DONE),
        (ExecutionStepRefused(execution_id=_ID, index=1, occurred_at=_NOW), StepOutcome.REFUSED),
        (
            ExecutionStepBroken(execution_id=_ID, index=1, cause="TimeoutError", occurred_at=_NOW),
            StepOutcome.BROKEN,
        ),
        (ExecutionStepSkipped(execution_id=_ID, index=1, occurred_at=_NOW), StepOutcome.SKIPPED),
    ],
    ids=["done", "refused", "broken", "skipped"],
)
def test_parking_a_walk_whose_last_reported_step_handed_nothing_off_is_refused(
    last: ExecutionEvent, outcome: StepOutcome
) -> None:
    """Furthest along the list decides, so an earlier handoff that already
    completed is not something a later parking can wait on."""
    state = _walk(_claimed(), _handed_off(0), _completed(_FIRST), last)
    with pytest.raises(ExecutionCannotBeParkedError, match=str(outcome)) as refused:
        decide_park(state, ParkExecution(execution_id=_ID), now=_NOW)
    assert refused.value.last is outcome


def test_claiming_a_ready_walk_takes_it_back() -> None:
    state = _walk(*_PARKED_AT_THE_MOVE, _completed(_SECOND))
    assert decide_claim(state, ClaimExecution(execution_id=_ID), now=_NOW) == [
        ExecutionClaimed(execution_id=_ID, occurred_at=_NOW)
    ]


def test_claiming_a_parked_walk_is_refused_while_its_work_runs() -> None:
    with pytest.raises(ExecutionCannotBeClaimedError, match="Parked") as refused:
        decide_claim(_walk(*_PARKED_AT_THE_MOVE), ClaimExecution(execution_id=_ID), now=_NOW)
    assert refused.value.status is ExecutionStatus.PARKED


def test_reporting_a_step_of_a_parked_walk_is_refused() -> None:
    """A driver walking past work that has not finished, which parking exists to stop."""
    with pytest.raises(ExecutionStepCannotBeReportedError) as refused:
        decide_step(
            _walk(*_PARKED_AT_THE_MOVE),
            ReportExecutionStep(execution_id=_ID, index=2, outcome=StepOutcome.DONE),
            now=_NOW,
        )
    assert refused.value.status is ExecutionStatus.PARKED


def test_reporting_a_step_of_a_ready_walk_is_accepted_as_a_dispatched_one_is() -> None:
    """Claiming is not a gate on reporting, and nothing a ready walk waits on is running."""
    events = decide_step(
        _walk(*_PARKED_AT_THE_MOVE, _completed(_SECOND)),
        ReportExecutionStep(execution_id=_ID, index=2, outcome=StepOutcome.DONE),
        now=_NOW,
    )
    assert events == [_done(2)]


def test_ending_a_parked_walk_is_allowed() -> None:
    """How a person stops a plan whose handed-off work should not be continued from."""
    assert decide_end(_walk(*_PARKED_AT_THE_MOVE), EndExecution(execution_id=_ID), now=_NOW) == [
        ExecutionEnded(execution_id=_ID, occurred_at=_NOW)
    ]


def test_a_parked_walk_folds_to_parked_with_the_steps_after_it_unreported() -> None:
    state = _walk(*_PARKED_AT_THE_MOVE)
    assert state.status is ExecutionStatus.PARKED
    assert [step.outcome for step in state.steps] == [
        StepOutcome.DONE,
        StepOutcome.HANDED_OFF,
        None,
    ]


def test_a_start_for_the_step_it_waits_on_leaves_a_parked_walk_parked() -> None:
    assert _walk(*_PARKED_AT_THE_MOVE, _started(_SECOND)).status is ExecutionStatus.PARKED


@pytest.mark.parametrize(
    "ending",
    [
        _completed(_SECOND),
        ExecutionStepEngineAborted(execution_id=_ID, step_id=_SECOND, occurred_at=_NOW),
        ExecutionStepEngineFailed(execution_id=_ID, step_id=_SECOND, occurred_at=_NOW),
    ],
    ids=["completed", "aborted", "failed"],
)
def test_an_ending_for_the_step_it_waits_on_folds_a_parked_walk_to_ready(
    ending: ExecutionEvent,
) -> None:
    state = _walk(*_PARKED_AT_THE_MOVE, _started(_SECOND), ending)
    assert state.status is ExecutionStatus.READY


def test_an_ending_for_another_step_leaves_a_parked_walk_parked() -> None:
    """A late ending for the collect, which finished inside its bound, says
    nothing about the move the walk is waiting on."""
    assert _walk(*_PARKED_AT_THE_MOVE, _completed(_FIRST)).status is ExecutionStatus.PARKED


def test_an_ending_that_landed_before_the_parking_folds_the_parking_to_ready() -> None:
    state = _walk(_claimed(), _done(0), _handed_off(1), _completed(_SECOND), _parked())
    assert state.status is ExecutionStatus.READY


def test_an_engine_report_on_a_ready_walk_leaves_it_ready() -> None:
    state = _walk(*_PARKED_AT_THE_MOVE, _completed(_SECOND), _completed(_FIRST))
    assert state.status is ExecutionStatus.READY


def test_a_claim_on_a_ready_walk_folds_back_to_claimed() -> None:
    state = _walk(*_PARKED_AT_THE_MOVE, _completed(_SECOND), _claimed())
    assert state.status is ExecutionStatus.CLAIMED


def test_the_last_reported_step_is_the_furthest_along_and_not_the_latest() -> None:
    state = _walk(_done(2), _done(0))
    assert state.last_reported is not None
    assert state.last_reported.id == _THIRD


def test_there_is_no_last_reported_step_before_any_step_is_reported() -> None:
    assert _walk(_claimed()).last_reported is None
