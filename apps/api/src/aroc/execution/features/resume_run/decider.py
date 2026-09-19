"""The decision: what resuming a run produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from aroc.execution.aggregates.run import (
    Run,
    RunCannotBeResumedError,
    RunNotFoundError,
    RunResumed,
    RunStatus,
)
from aroc.execution.features.resume_run.command import ResumeRun


def decide(
    state: Run | None,
    command: ResumeRun,
    *,
    now: datetime,
) -> list[RunResumed]:
    """Decide the events produced by resuming a run.

    Invariants:
      - State must not be None, or no such run was recorded
        -> RunNotFoundError
      - The run must be paused
        -> RunCannotBeResumedError

    The mirror of the pause decider, and the only one on this aggregate
    whose single admitted source state is not `RUNNING`. A run that is
    already running is refused rather than absorbed: two reporters
    disagreeing about whether the engine ever stopped is worth surfacing,
    and silently accepting the second would write a resume with no pause
    before it onto a log nobody can edit.
    """
    if state is None:
        raise RunNotFoundError(command.run_id)
    if state.status is not RunStatus.PAUSED:
        raise RunCannotBeResumedError(command.run_id, state.status)
    return [RunResumed(run_id=command.run_id, occurred_at=now)]


__all__ = ["decide"]
