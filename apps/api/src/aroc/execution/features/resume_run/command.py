"""The intent: record that this run carried on from where it paused."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ResumeRun:
    """Mark the run with this id as running again.

    Carries the id because it names a run that already exists rather than
    asking for a new one. The timestamp is still the handler's to supply
    from a port.

    The verb does not claim this system resumed the run. Like its pair
    and like the three endings, it records a move somebody else made, and
    which of the two ways a run can arrive was settled at its genesis.

    The one command on this aggregate that returns a run to a status it
    already held. That is a fact about the fold rather than about the
    command: the stream still only grows, and a resume is one more row on
    it.
    """

    run_id: UUID


__all__ = ["ResumeRun"]
