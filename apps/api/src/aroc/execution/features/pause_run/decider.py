"""The decision: what pausing a run produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from aroc.execution.aggregates.run import (
    Run,
    RunCannotBePausedError,
    RunNotFoundError,
    RunPaused,
    RunStatus,
)
from aroc.execution.features.pause_run.command import PauseRun


def decide(
    state: Run | None,
    command: PauseRun,
    *,
    now: datetime,
) -> list[RunPaused]:
    """Decide the events produced by pausing a run.

    Invariants:
      - State must not be None, or no such run was recorded
        -> RunNotFoundError
      - The run must be running
        -> RunCannotBePausedError

    The guard compares against `RUNNING` rather than asking `has_ended`,
    which is the difference between this decider and the three endings.
    They refuse only from a terminal, because an ending is legitimate on
    a paused run; this also refuses from `PAUSED`, where the run is live
    and still cannot take the move.

    A second pause is refused rather than absorbed, for the reason the
    endings give: two reporters each believing they stopped a running run
    should not both be told they did. The refusal carries the status the
    run is actually in, because that is the fact the losing caller does
    not have.
    """
    if state is None:
        raise RunNotFoundError(command.run_id)
    if state.status is not RunStatus.RUNNING:
        raise RunCannotBePausedError(command.run_id, state.status)
    return [RunPaused(run_id=command.run_id, occurred_at=now)]


__all__ = ["decide"]
