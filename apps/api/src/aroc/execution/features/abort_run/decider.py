"""The decision: what aborting a run produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from aroc.execution.aggregates.run import (
    Run,
    RunAborted,
    RunCannotBeAbortedError,
    RunNotFoundError,
)
from aroc.execution.features.abort_run.command import AbortRun


def decide(
    state: Run | None,
    command: AbortRun,
    *,
    now: datetime,
) -> list[RunAborted]:
    """Decide the events produced by aborting a run.

    Invariants:
      - State must not be None, or no such run was recorded
        -> RunNotFoundError
      - The run must not have ended already
        -> RunCannotBeAbortedError

    An already-ended run is refused rather than absorbed, and the
    refusal carries the status it is actually in. A caller aborting a run
    that completed a second earlier needs to know which of the two
    happened, not merely that they lost.

    Aborting is refused from every terminal including `Failed`, which is
    worth a thought rather than an assumption: a run that broke was not
    then stopped by anyone, and recording both would put two endings on
    one stream. The first ending is the one that happened.
    """
    if state is None:
        raise RunNotFoundError(command.run_id)
    if state.has_ended:
        raise RunCannotBeAbortedError(command.run_id, state.status)
    return [RunAborted(run_id=command.run_id, occurred_at=now)]


__all__ = ["decide"]
