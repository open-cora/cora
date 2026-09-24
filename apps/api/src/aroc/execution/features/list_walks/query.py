"""The question: which walks, newest first, and where do I carry on from?

The query a fold cannot answer. `GetWalk` names the walk it wants; this
one is asking which walk to name, and the only way to answer that from
an event log is to have kept a summary of it as the events arrived.

Three parameters and they are three different kinds of thing. The filter
says which walks. The limit says how many of them. The cursor says where
the last page stopped.

No classmethod wrapping the filter, unlike the plan and procedure lists.
A procedure id is a UUID and both surfaces parse it before a query
exists, so there is nothing left for the domain to refuse.
"""

from dataclasses import dataclass
from uuid import UUID

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

    `procedure_id` narrows to the walks dispatched for that procedure,
    which is the question this slice exists for: a routine composed once
    is walked every time it runs, so "how did this procedure go" means
    reading its walks.

    Not guaranteed to match at most one walk, and not meant to be. The
    interesting page is usually several: the same procedure run at
    different times, some ended and some not.
    """

    procedure_id: UUID | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListWalks"]
