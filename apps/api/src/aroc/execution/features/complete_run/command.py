"""The intent: record that this run reached its own end."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aroc.execution.aggregates.run import normalize_occurred_at


@dataclass(frozen=True)
class CompleteRun:
    """Mark the run with this id as having completed.

    Carries the id because it names a run that already exists rather than
    asking for a new one.

    `occurred_at` is when the engine did this, as the caller reports it,
    and it is optional: a caller who omits it gets the moment the report
    arrived, which is the best this system could otherwise guess. It is
    accepted here and not on the commands that author a plan, a policy or
    an actor, because those are acts this system performs and the moment
    it writes one IS the moment it happened. See R8 in
    docs/reference/naming.md.

    The verb does not claim this system ended the run. Which of the two
    ways a run can arrive was settled at its genesis, and an ending is
    read the same way the rest of the stream is: a run opened by a report
    is one this system was told about, so its ending was reported too.
    That is why the three ending commands take no reporting verb of their
    own, where the genesis command had to.
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


__all__ = ["CompleteRun"]
