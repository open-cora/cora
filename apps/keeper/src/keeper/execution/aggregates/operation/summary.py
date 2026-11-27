"""One row per operation, and the port that reads those rows.

The Execution's sibling, and the same shape for the same reason:
`read.py` answers a question that names an operation, and this answers
the ones that do not. Which operation is called `count`, and what can be
run at all.

## Why a name lookup cannot promise one answer

Two operations may deliberately share a name. The Operation state module
says why: one routine constrained two ways is two operations, and which
one a run step cites is what says how it was constrained. So this returns
a page, and a caller asking by name has to decide what more than one
means.

That decision is the caller's and not this system's. An operator who
wants one answer pins an operation id; a caller that cannot choose refuses and
says so. Either is better than this picking quietly, which would mean
choosing for every caller on the strength of an ordering none of them
asked about.

## Why a retired operation is left out unless asked for

The question a listing answers is what can be run, and a retired
operation cannot be: nothing may cite it. Listing it by default would
make every caller that resolves a name filter it out again, and the one
that forgot would compose around it and be refused. It would also undo
one reason to retire an operation, a second definition of a name that
should have been the only one: retiring the older leaves one row under
that name only if the listing leaves the older out.

So `include_retired` is the one switch, and it widens rather than
narrows. A reader auditing the record turns it on and every row says
which it is.

## Why the row is so thin

`parameters_schema` is not here. It is unbounded, it is the largest thing
an operation carries, and a page of them is a page of schemas. A caller that
wants one has the operation id and one more call.

There is no `updated_at` either. The two things that can happen to an
operation after its definition are a declaration of its device use and
its retirement, and `drives_devices` and `status` say whether each has;
when is on the events, and nothing reading a list has asked for it.

## Why the device use rides the row

`drives_devices` is on the row because the caller that most needs it reads
a listing: whatever keeps a facility's operations in step with a register
looks each one up by name and has to tell an operation nobody declared
from one declared either way, without a second read per row. It is one
nullable boolean, which costs nothing a page of fifty notices.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.operation.state import OperationName, OperationStatus


@dataclass(frozen=True)
class OperationSummary:
    """An operation as a list shows it.

    `created_at` is when the operation was defined, taken from the envelope's
    domain time. For an operation the two times the envelope carries are the
    same instant to within a round trip, because an operation is authored here
    rather than reported from somewhere else, which is the R8 line the
    whole context is drawn along.

    `status` is derived, by the projection from the event type the same
    way the fold derives it, because a row that stored a status a writer
    could set is a row a writer could set wrong.

    `drives_devices` is the facility's declaration, copied off its event,
    and None while nobody has made one, exactly as on the aggregate.
    """

    operation_id: UUID
    name: OperationName
    status: OperationStatus
    drives_devices: bool | None
    created_at: datetime


@dataclass(frozen=True)
class OperationSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. Opaque on purpose:
    it encodes the sort key of the final row, and a caller that takes it
    apart is depending on an ordering this is free to change.
    """

    items: list[OperationSummary]
    next_cursor: str | None


class OperationSummaryLookup(Protocol):
    """Read operations by something other than their id."""

    async def list_operations(
        self,
        *,
        name: OperationName | None,
        include_retired: bool,
        limit: int,
        cursor: str | None,
    ) -> OperationSummaryPage:
        """Return one page of operations, newest first.

        `name` narrows to the operations carrying exactly that name, which may
        be none, one, or several, and the several is the case worth
        designing for.

        `include_retired` adds the operations this system no longer offers.
        Off, a page holds active operations alone. It has no default here,
        for the reason the procedure port gives about its filters: an
        adapter that may omit it is one a caller can silently lose it to.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["OperationSummary", "OperationSummaryLookup", "OperationSummaryPage"]
