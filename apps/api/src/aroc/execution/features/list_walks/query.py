"""The question: which walks, newest first, and where do I carry on from?

The query a fold cannot answer. `GetWalk` names the walk it wants; this
one is asking which walk to name, and the only way to answer that from
an event log is to have kept a summary of it as the events arrived.

Three parameters and they are three different kinds of thing. The filter
says which walks. The limit says how many of them. The cursor says where
the last page stopped.
"""

from dataclasses import dataclass

from aroc.execution.aggregates.walk.state import InvalidWalkFilterError
from aroc.shared.identifier import Identifier

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many walks one page carries, by default and at most.

A default rather than everything, because a beamline running for a year
has more walks than any caller meant to ask for. A maximum rather than
trusting the number sent, because the cost of a page is paid by the
server.
"""


@dataclass(frozen=True)
class ListWalks:
    """Read a page of walks, newest first.

    `reference` is the driver's own name for a walk, and the reason this
    slice exists: something holding the reference it minted and no walk
    id has nothing else to ask by.

    Not guaranteed to match at most one walk. Nothing stops two records
    of a single walk, so this answers with however many there are and
    lets the caller see the duplicate rather than hiding it behind a
    lookup that can only return one.
    """

    reference: Identifier | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None

    @classmethod
    def with_reference(
        cls,
        *,
        scheme: str | None,
        value: str | None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> "ListWalks":
        """Build a query from the two halves a surface receives separately.

        A `classmethod` rather than a check in `__post_init__`, because
        the field is one optional `Identifier` and by the time it exists
        the halves have already been paired. This is the only place that
        pairing happens, which is the shape `ListRuns` already uses for
        the same reason.
        """
        if (scheme is None) != (value is None):
            raise InvalidWalkFilterError(scheme, value)
        reference = (
            Identifier(scheme=scheme, value=value)
            if scheme is not None and value is not None
            else None
        )
        return cls(reference=reference, limit=limit, cursor=cursor)


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListWalks"]
