"""The question: which runs, newest first, and where do I carry on from?

The query a fold cannot answer. `GetRun` names the run it wants; this one
is asking which run to name, and the only way to answer that from an event
log is to have kept a summary of it as the events arrived.

Three parameters and they are three different kinds of thing. The filter
says which runs. The limit says how many of them. The cursor says where the
last page stopped.
"""

from dataclasses import dataclass

from aroc.execution.aggregates.run.state import InvalidRunFilterError
from aroc.shared.identifier import Identifier

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many runs one page carries, by default and at most.

A default rather than everything, because a deployment that has been
running for a year has more runs than any caller meant to ask for. A
maximum rather than trusting the number sent, because the cost of a page
is paid by the server and a caller asking for a million rows should get a
hundred instead of an outage.
"""


@dataclass(frozen=True)
class ListRuns:
    """Read a page of runs, newest first.

    `external_ref` is the engine's own identifier for a run, and the
    reason this slice exists: an adapter that restarts holds the engine's
    id and nothing else, and until now nothing in the API accepted one.

    Not guaranteed to match at most one run. Nothing stops two records of
    a single engine run, so this answers with however many there are and
    lets the caller see the duplicate rather than hiding it behind a
    lookup that can only return one.
    """

    external_ref: Identifier | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None

    @classmethod
    def with_external_ref(
        cls,
        *,
        scheme: str | None,
        value: str | None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> "ListRuns":
        """Build a query from the two halves a surface receives separately.

        Both surfaces take the scheme and the value as two parameters,
        because `Identifier` puts no pattern on a scheme and a single
        `scheme:value` string could not be split with any confidence. That
        makes "exactly one half arrived" a shape both of them can produce,
        so the refusal lives here rather than twice at the edges.

        A `classmethod` rather than a check in `__post_init__`, because
        the field is one optional `Identifier` and by the time it exists
        the halves have already been paired. This is the only place that
        pairing happens.
        """
        if (scheme is None) != (value is None):
            raise InvalidRunFilterError(scheme, value)
        external_ref = (
            Identifier(scheme=scheme, value=value)
            if scheme is not None and value is not None
            else None
        )
        return cls(external_ref=external_ref, limit=limit, cursor=cursor)


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListRuns"]
