"""The intent: record that this run stopped where it was."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class PauseRun:
    """Mark the run with this id as paused.

    Carries the id because it names a run that already exists rather than
    asking for a new one. The timestamp is still the handler's to supply
    from a port.

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


__all__ = ["PauseRun"]
