"""The question: what does this system hold about this walk?"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class GetWalk:
    """Read the walk with this id, and every step it holds.

    By this system's id, not by the driver's own reference. Finding a
    walk from a reference is the other question, and a fold cannot
    answer it: it would mean replaying every walk stream to see which
    one matches. That query needs a maintained table and a slice of its
    own.

    This is the only read that returns the steps. A listing drops them,
    because they are the largest thing a walk carries and a page of
    fifty would be almost nothing else.
    """

    walk_id: UUID


__all__ = ["GetWalk"]
