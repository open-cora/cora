"""The intent: record that this run broke."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aroc.execution.aggregates.run import normalize_occurred_at


@dataclass(frozen=True)
class FailRun:
    """Mark the run with this id as having failed.

    Carries the id because it names a run that already exists rather than
    asking for a new one.

    `occurred_at` is when the engine did this, as the caller reports it,
    and it is optional: a caller who omits it gets the moment the report
    arrived, which is the best this system could otherwise guess. It is
    accepted here and not on the commands that author a plan, a policy or
    an actor, because those are acts this system performs and the moment
    it writes one IS the moment it happened. See R8 in
    docs/reference/naming.md.

    `FailRun` reads as an instruction to break something, which it is
    not, and the name survives that because the family is worth more than
    the sentence. Three endings named for three verbs let a reader guess
    any one of them from the other two; one renamed for grace would break
    the pattern and the event it derives.

    Carries no message. The engine's own error text is the most useful
    thing this command could hold and the most dangerous place to put it,
    because it is unbounded text on a row that cannot be edited. It waits
    for somewhere deletable to keep it.
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


__all__ = ["FailRun"]
