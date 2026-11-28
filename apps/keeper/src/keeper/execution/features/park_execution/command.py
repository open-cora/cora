"""The intent: record that a walk stopped at work still running elsewhere."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from keeper.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class ParkExecution:
    """Park the execution with this id until the work a step handed off stops.

    Park, and not pause or suspend. Both of those are things done to
    something still running, and an engine already pauses and resumes a
    run on its own axis here. A parked walk has stopped, and what is
    still running is the work one of its steps handed to somewhere else.

    Sent in place of an ending, by the driver that reported the handed-off
    step, when it has more steps to walk or the work still to hear about.
    The execution is taken back by a claim once whatever watches that work
    reports it stopped, which is when the fold reads it as ready.

    `occurred_at` is when the walk stopped, as the caller reports it, and
    it is optional: a caller who omits it gets the moment the report
    arrived. Accepted for the reason an ending accepts one, because the
    driver stopped on its own clock and this system was told afterwards.
    """

    execution_id: UUID
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        """Refuse a naive timestamp and store the UTC form of an aware one.

        Frozen, so the normalised value goes back through
        `object.__setattr__`, the way the shared identifier does it.
        """
        if self.occurred_at is not None:
            object.__setattr__(self, "occurred_at", normalize_occurred_at(self.occurred_at))


__all__ = ["ParkExecution"]
