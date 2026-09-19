"""The question: what does this system hold about this run?"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetRun:
    """Read the run with this id.

    By this system's id for the run, not by the engine's. Finding a run
    from an external reference is the other question, and a fold cannot
    answer it: it would mean replaying every run stream to see which one
    matches. That query needs a maintained table and a slice of its own.
    """

    run_id: UUID


__all__ = ["GetRun"]
