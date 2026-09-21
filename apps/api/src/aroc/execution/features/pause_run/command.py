"""The intent: record that this run stopped where it was."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aroc.shared.instant import normalize_occurred_at


@dataclass(frozen=True)
class PauseRun:
    """Mark the run with this id as paused.

    Carries the id because it names a run that already exists rather than
    asking for a new one.

    `occurred_at` is when the engine did this, as the caller reports it,
    and it is optional: a caller who omits it gets the moment the report
    arrived, which is the best this system could otherwise guess. It is
    accepted here and not on the commands that author a plan, a policy or
    an actor, because those are acts this system performs and the moment
    it writes one IS the moment it happened. See R8 in
    docs/reference/naming.md.

    The verb does not claim this system paused the run, the same way the
    three ending verbs do not claim it ended one. Which of the two ways a
    run can arrive was settled at its genesis, and every later command on
    the stream is read through that: a run opened by a report is one this
    system was told about, so its pause was reported too.

    Nothing describes the pause. Where the engine stopped, and what it is
    waiting for, are the engine's to hold; this records only that it
    stopped, which is the part a reader of this system can act on.
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


__all__ = ["PauseRun"]
