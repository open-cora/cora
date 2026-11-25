"""The question: what did this run produce?

The query this bounded context exists for, and the one a fold cannot
answer. `GetDataset` names the dataset it wants; this one is asking which
dataset to name, and the only way to answer that from an event log is to
have kept a summary of it as the events arrived.

Four parameters and they are three different kinds of thing. The two
filters say which datasets. The limit says how many of them. The cursor
says where the last page stopped.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.custody.aggregates.dataset.state import InvalidDatasetFilterError
from keeper.shared.identifier import Identifier

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many datasets one page carries, by default and at most.

The same two numbers the sibling context uses, and deliberately the same
rather than tuned: a page size is a property of the surface rather than
of what is on the page, and a caller paging two lists should not have to
learn two conventions.
"""


@dataclass(frozen=True)
class ListDatasets:
    """Read a page of datasets, newest first.

    `step_id` narrows to what one run produced, which is the whole reason
    this slice exists. It is a keeper id rather than an engine's, because
    that is what the record carries.

    Nothing here turns an engine's own reference into one. A step carries
    that reference and no slice is keyed on it, so a caller holding one
    already knows the execution it belongs to, or it has nothing to ask
    with. That is deliberate rather than missing: whatever dispatched the
    work carried both ids into the engine's metadata, so the side that
    holds an engine reference holds the keeper's ids beside it.

    Not guaranteed to match at most one dataset. How many datasets a run
    produces is the reporting side's policy rather than a rule here, so
    this answers with however many there are.

    `address_prefix` narrows to the datasets holding an address in one
    scheme whose value starts with the given string. It is how whatever
    moved data asks what it carried: a move knows a place and a path, and
    the datasets it moved are the ones with an address at or under that
    path. Matched as a plain prefix and nothing more, because a value is
    a store's own spelling: the caller decides where a boundary falls,
    which for a folder is a value ending in a slash.

    The two filters combine.
    """

    step_id: UUID | None = None
    address_prefix: Identifier | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None

    @classmethod
    def with_address_prefix(
        cls,
        *,
        scheme: str | None,
        prefix: str | None,
        step_id: UUID | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> "ListDatasets":
        """Build a query from the two halves a surface receives separately.

        A surface takes the scheme and the prefix as two parameters, for the
        reason the device listing gives: a single scheme:value string could
        not be split with any confidence. So "exactly one half arrived" is a
        shape both surfaces can produce, and the refusal lives here once.
        """
        if (scheme is None) != (prefix is None):
            raise InvalidDatasetFilterError(scheme, prefix)
        address_prefix = (
            Identifier(scheme=scheme, value=prefix)
            if scheme is not None and prefix is not None
            else None
        )
        return cls(step_id=step_id, address_prefix=address_prefix, limit=limit, cursor=cursor)


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListDatasets"]
