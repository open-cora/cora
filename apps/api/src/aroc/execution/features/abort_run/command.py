"""The intent: record that something outside this run stopped it."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aroc.execution.aggregates.run import normalize_occurred_at


@dataclass(frozen=True)
class AbortRun:
    """Mark the run with this id as having been aborted.

    Carries the id because it names a run that already exists rather than
    asking for a new one.

    `occurred_at` is when the engine did this, as the caller reports it,
    and it is optional: a caller who omits it gets the moment the report
    arrived, which is the best this system could otherwise guess. It is
    accepted here and not on the commands that author a plan, a policy or
    an actor, because those are acts this system performs and the moment
    it writes one IS the moment it happened. See R8 in
    docs/reference/naming.md.

    Aborted is the ending where somebody or something decided to stop the
    run. The run failing on its own is the sibling command, and the two
    stay apart because the engines this system hears from tell them
    apart; collapsing them would discard a distinction the source already
    drew.

    No field says who or what did the stopping. The envelope already
    names the principal that issued this command, and anything more is a
    free-text field on a row that cannot be edited.
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


__all__ = ["AbortRun"]
