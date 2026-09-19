"""The decision: what failing a run produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from aroc.execution.aggregates.run import (
    Run,
    RunCannotBeFailedError,
    RunFailed,
    RunNotFoundError,
)
from aroc.execution.features.fail_run.command import FailRun


def decide(
    state: Run | None,
    command: FailRun,
    *,
    now: datetime,
) -> list[RunFailed]:
    """Decide the events produced by recording that a run failed.

    Invariants:
      - State must not be None, or no such run was recorded
        -> RunNotFoundError
      - The run must not have ended already
        -> RunCannotBeFailedError

    An already-ended run is refused rather than absorbed, and the
    refusal carries the status it is actually in.

    Failing is refused from `Completed` too, which is the case worth
    naming: an engine that reported success and then crashed on the way
    out looks exactly like this, and the honest answer is that this
    system cannot tell which report was right. Refusing keeps the first
    one and makes the disagreement visible as a 409, where accepting the
    second would quietly overwrite a claim somebody already made.
    """
    if state is None:
        raise RunNotFoundError(command.run_id)
    if state.has_ended:
        raise RunCannotBeFailedError(command.run_id, state.status)
    return [RunFailed(run_id=command.run_id, occurred_at=now)]


__all__ = ["decide"]
