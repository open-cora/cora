"""The intent: record that this run carried on from where it paused."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aroc.execution.aggregates.run import normalize_occurred_at


@dataclass(frozen=True)
class ResumeRun:
    """Mark the run with this id as running again.

    Carries the id because it names a run that already exists rather than
    asking for a new one.

    `occurred_at` is when the engine did this, as the caller reports it,
    and it is optional: a caller who omits it gets the moment the report
    arrived, which is the best this system could otherwise guess. It is
    accepted here and not on the commands that author a plan, a policy or
    an actor, because those are acts this system performs and the moment
    it writes one IS the moment it happened. See R8 in
    docs/reference/naming.md.

    The verb does not claim this system resumed the run. Like its pair
    and like the three endings, it records a move somebody else made, and
    which of the two ways a run can arrive was settled at its genesis.

    The one command on this aggregate that returns a run to a status it
    already held. That is a fact about the fold rather than about the
    command: the stream still only grows, and a resume is one more row on
    it.
    """

    run_id: UUID
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["ResumeRun"]
