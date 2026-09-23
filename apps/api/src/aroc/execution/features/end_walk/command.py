"""The intent: record that a walk is over and nothing more is coming."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aroc.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class EndWalk:
    """Close the walk with this id.

    End, not complete and not finish. Both of those would say how it
    went, and this command says only that the driver has no more to
    report: a walk that stopped at its first failure ends exactly like
    one that ran every step. How it went is on the steps.

    A bare imperative rather than a reporting verb, for the reason the
    run's three endings are bare. Which of the two ways a walk can arrive
    was settled at its genesis, so an ending on a stream a report opened
    was reported too, and repeating the word here would say it twice.

    `occurred_at` is when the walk ended, as the caller reports it, and
    it is optional: a caller who omits it gets the moment the report
    arrived.
    """

    walk_id: UUID
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["EndWalk"]
