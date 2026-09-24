"""The decision: what relaying an engine's account of a step produces.

Pure. No awaits, no ports, no clock. `now` arrives as a parameter
precisely so this function has nothing to invent.
"""

from datetime import datetime

from aroc.execution.aggregates.walk import (
    EngineReport,
    EngineState,
    InvalidStepRunReportError,
    Walk,
    WalkNotFoundError,
    WalkStep,
    WalkStepNotFoundError,
    WalkStepRunAborted,
    WalkStepRunCompleted,
    WalkStepRunFailed,
    WalkStepRunPaused,
    WalkStepRunResumed,
    WalkStepRunStarted,
)
from aroc.execution.features.report_step_run.command import ReportStepRun

StepRunEvent = (
    WalkStepRunStarted
    | WalkStepRunPaused
    | WalkStepRunResumed
    | WalkStepRunCompleted
    | WalkStepRunAborted
    | WalkStepRunFailed
)
"""The six events this slice can produce, one per thing an engine did."""

_FOLLOWS: dict[EngineReport, frozenset[EngineState | None]] = {
    EngineReport.STARTED: frozenset({None}),
    EngineReport.PAUSED: frozenset({EngineState.RUNNING}),
    EngineReport.RESUMED: frozenset({EngineState.PAUSED}),
    EngineReport.COMPLETED: frozenset({EngineState.RUNNING, EngineState.PAUSED}),
    EngineReport.ABORTED: frozenset({EngineState.RUNNING, EngineState.PAUSED}),
    EngineReport.FAILED: frozenset({EngineState.RUNNING, EngineState.PAUSED}),
}
"""Which engine states each report may follow.

A table rather than six branches of ifs, because the question is the same
one asked six times and the answer is data.

`None` appears once, against a start, which is what makes a start the
genesis of this second account and every other report a transition on it.
The three terminals appear in no value, so nothing follows an ending: an
engine that reported success and then crashed on the way out looks
exactly like a late failure, and this system cannot tell which report was
right. Keeping the first and refusing the second makes the disagreement
visible where accepting it would overwrite a claim somebody already made.

All three endings are reachable from `PAUSED` as well as from `RUNNING`,
which is the edge most easily got wrong. A paused run is exactly the one
an operator aborts.
"""


def _find(state: Walk, command: ReportStepRun) -> WalkStep:
    for step in state.steps:
        if step.id == command.step_id:
            return step
    raise WalkStepNotFoundError(state.id, command.step_id)


def decide(
    state: Walk | None,
    command: ReportStepRun,
    *,
    now: datetime,
) -> list[StepRunEvent]:
    """Decide the events produced by relaying an engine's account.

    Invariants:
      - State must not be None, or no such walk was dispatched
        -> WalkNotFoundError
      - The walk must hold a step with that id
        -> WalkStepNotFoundError
      - The report must follow the engine state already recorded
        -> InvalidStepRunReportError

    What is deliberately NOT checked is the step's own outcome. A driver
    may report its call returning before or after the engine reports the
    run ending, because the two come from different clients that do not
    know about each other, and requiring an order would refuse whichever
    happened to arrive first.

    A walk that has ended is not checked either, and that is the same
    decision. An engine's account of a run can arrive after a driver gave
    up and closed the walk; refusing it would throw away the one record
    that says what the hardware actually did.
    """
    if state is None:
        raise WalkNotFoundError(command.walk_id)
    step = _find(state, command)
    if step.engine_state not in _FOLLOWS[command.reported]:
        raise InvalidStepRunReportError(
            command.step_id, holds=step.engine_state, got=command.reported.value
        )
    match command.reported:
        case EngineReport.STARTED:
            return [
                WalkStepRunStarted(
                    walk_id=command.walk_id,
                    step_id=command.step_id,
                    engine_reference=command.engine_reference,
                    occurred_at=now,
                )
            ]
        case EngineReport.PAUSED:
            return [
                WalkStepRunPaused(
                    walk_id=command.walk_id, step_id=command.step_id, occurred_at=now
                )
            ]
        case EngineReport.RESUMED:
            return [
                WalkStepRunResumed(
                    walk_id=command.walk_id, step_id=command.step_id, occurred_at=now
                )
            ]
        case EngineReport.COMPLETED:
            return [
                WalkStepRunCompleted(
                    walk_id=command.walk_id, step_id=command.step_id, occurred_at=now
                )
            ]
        case EngineReport.ABORTED:
            return [
                WalkStepRunAborted(
                    walk_id=command.walk_id, step_id=command.step_id, occurred_at=now
                )
            ]
        case EngineReport.FAILED:
            return [
                WalkStepRunFailed(
                    walk_id=command.walk_id, step_id=command.step_id, occurred_at=now
                )
            ]


__all__ = ["StepRunEvent", "decide"]
