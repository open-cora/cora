"""The decision: what claiming a walk produces.

Pure. No awaits, no ports, no clock. `now` arrives as a parameter
precisely so this function has nothing to invent.
"""

from datetime import datetime

from aroc.execution.aggregates.walk import (
    Walk,
    WalkCannotBeClaimedError,
    WalkClaimed,
    WalkNotFoundError,
    WalkStatus,
)
from aroc.execution.features.claim_walk.command import ClaimWalk


def decide(
    state: Walk | None,
    command: ClaimWalk,
    *,
    now: datetime,
) -> list[WalkClaimed]:
    """Decide the events produced by claiming a walk.

    Invariants:
      - State must not be None, or no such walk was dispatched
        -> WalkNotFoundError
      - The walk must be dispatched and not yet taken up
        -> WalkCannotBeClaimedError

    Refused from every status but `DISPATCHED`, which makes this the only
    command on this stream that refuses from a live status as well as
    from the terminal one. The pair a run offers for pause and resume is
    the precedent, and the reason is the same: the two live refusals mean
    different things and a caller needs the status to tell them apart.

    A second claim is the one worth stating. Two drivers each believing
    they own one traversal is the failure the status exists to make
    visible, and nothing here can stop the second one from moving a
    motor. What it can do is refuse to record that the walk was taken up
    twice, so the disagreement ends up in the log rather than only at the
    beamline.

    Claiming is not a gate on reporting. A driver that reports a step
    without claiming first moves the walk straight from dispatched to
    running, and that is allowed: a claim says who has the work, and
    refusing the report would lose a fact this system was told in order
    to enforce an ordering the log does not have.
    """
    if state is None:
        raise WalkNotFoundError(command.walk_id)
    if state.status is not WalkStatus.DISPATCHED:
        raise WalkCannotBeClaimedError(command.walk_id, state.status)
    return [WalkClaimed(walk_id=command.walk_id, occurred_at=now)]


__all__ = ["decide"]
