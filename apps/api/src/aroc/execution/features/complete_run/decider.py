"""The decision: what completing a run produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from aroc.execution.aggregates.run import (
    Run,
    RunCannotBeCompletedError,
    RunCompleted,
    RunNotFoundError,
)
from aroc.execution.features.complete_run.command import CompleteRun


def decide(
    state: Run | None,
    command: CompleteRun,
    *,
    now: datetime,
) -> list[RunCompleted]:
    """Decide the events produced by completing a run.

    Invariants:
      - State must not be None, or no such run was recorded
        -> RunNotFoundError
      - The run must not have ended already
        -> RunCannotBeCompletedError

    The second refusal reads the status through `has_ended` rather than
    comparing against a tuple of terminals. A fourth terminal would then
    be one edit on the aggregate rather than three edits across three
    deciders, one of which would be forgotten.

    A run that already ended is refused rather than absorbed, for the
    reason the Actor's switch gives: two callers each believing they
    closed a live run should not both be told they did. The refusal
    carries the status the run is actually in, because that is the fact
    the losing caller does not have.
    """
    if state is None:
        raise RunNotFoundError(command.run_id)
    if state.has_ended:
        raise RunCannotBeCompletedError(command.run_id, state.status)
    return [RunCompleted(run_id=command.run_id, occurred_at=now)]


__all__ = ["decide"]
