"""The intent: record that this run broke."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class FailRun:
    """Mark the run with this id as having failed.

    Carries the id because it names a run that already exists rather than
    asking for a new one. The timestamp is still the handler's to supply
    from a port.

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


__all__ = ["FailRun"]
