"""The decision: what ending a walk produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from aroc.execution.aggregates.walk import (
    Walk,
    WalkAlreadyEndedError,
    WalkEnded,
    WalkNotFoundError,
)
from aroc.execution.features.end_walk.command import EndWalk


def decide(
    state: Walk | None,
    command: EndWalk,
    *,
    now: datetime,
) -> list[WalkEnded]:
    """Decide the events produced by ending a walk.

    Invariants:
      - State must not be None, or no such walk was recorded
        -> WalkNotFoundError
      - The walk must not have ended already
        -> WalkAlreadyEndedError

    A walk with steps still unreported is ended anyway, and refusing
    that would be the wrong rule. A driver that stopped at its first
    failure reports the rest as skipped and then ends, but a driver that
    was killed reports nothing further at all, and the walk that gets
    ended afterwards is exactly the one whose record is incomplete.
    Requiring every step first would mean the only walks that could be
    closed are the ones that did not need closing.

    An already-ended walk is refused rather than absorbed, for the
    reason a run's endings are: two callers each believing they closed a
    live walk should not both be told they did.
    """
    if state is None:
        raise WalkNotFoundError(command.walk_id)
    if state.ended:
        raise WalkAlreadyEndedError(command.walk_id)
    return [WalkEnded(walk_id=command.walk_id, occurred_at=now)]


__all__ = ["decide"]
