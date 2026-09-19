"""The intent: record that this run reached its own end."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class CompleteRun:
    """Mark the run with this id as having completed.

    Carries the id because it names a run that already exists rather than
    asking for a new one. The timestamp is still the handler's to supply
    from a port.

    The verb does not claim this system ended the run. Which of the two
    ways a run can arrive was settled at its genesis, and an ending is
    read the same way the rest of the stream is: a run opened by a report
    is one this system was told about, so its ending was reported too.
    That is why the three ending commands take no reporting verb of their
    own, where the genesis command had to.
    """

    run_id: UUID


__all__ = ["CompleteRun"]
