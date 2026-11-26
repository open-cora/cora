"""One row per procedure, and the port that reads those rows.

The Operation's sibling, and the same shape for the same reason: `read.py`
answers a question that names a procedure, and this answers the ones
that do not. Which procedure is called `tomography`, and what has been
composed at all.

## Why a name lookup cannot promise one answer

Two procedures may share a name, for the reason two operations may: one
routine composed two ways is two procedures, and which one an execution
cites is what says how it was composed. So this returns a page, and a
caller asking by name has to decide what more than one means. That
decision is the caller's; this picking quietly would mean choosing on
the strength of an ordering nobody asked about.

## Why a retired procedure is left out unless asked for

The question a listing answers is what this system can be asked to run,
and what one station can, and a retired procedure is neither: a dispatch
of it is refused. Listing it by default would leave every caller that
resolves a name or a station's routines to filter it out again, and the
one that forgot would dispatch it and be refused. The operation summary
gives the same reason at more length.

So `include_retired` is the one switch, and it widens rather than
narrows. A reader auditing the record turns it on and every row says
which it is.

## Why the steps are not on the row

A procedure may hold a thousand of them, so a page of fifty would be
almost entirely steps. What a list needs instead is how long the routine
is, which is one integer, and a caller that wants the steps has the id
and one more call. That is the same split `GET /executions` already draws.

There is no `updated_at`. The one thing that can happen to a procedure
after it is composed is its retirement, and `status` says whether it
has; when it did is on the event, and nothing reading a list has asked
for it.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.procedure.state import (
    ProcedureBeamline,
    ProcedureName,
    ProcedureStatus,
)


@dataclass(frozen=True)
class ProcedureSummary:
    """A procedure as a list shows it.

    `created_at` is when the procedure was defined, taken from the
    envelope's domain time. For a procedure the two times the envelope
    carries are the same instant to within a round trip, because a
    procedure is authored here rather than reported from somewhere else,
    which is the R8 line the whole context is drawn along.

    `status` is derived, by the projection from the event type the same
    way the fold derives it, because a row that stored a status a writer
    could set is a row a writer could set wrong.
    """

    procedure_id: UUID
    name: ProcedureName
    beamline: ProcedureBeamline
    step_count: int
    status: ProcedureStatus
    created_at: datetime


@dataclass(frozen=True)
class ProcedureSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. Opaque on purpose:
    it encodes the sort key of the final row, and a caller that takes it
    apart is depending on an ordering this is free to change.
    """

    items: list[ProcedureSummary]
    next_cursor: str | None


class ProcedureSummaryLookup(Protocol):
    """Read procedures by something other than their id."""

    async def list_procedures(
        self,
        *,
        name: ProcedureName | None,
        beamline: ProcedureBeamline | None,
        include_retired: bool,
        limit: int,
        cursor: str | None,
    ) -> ProcedureSummaryPage:
        """Return one page of procedures, newest first.

        `name` narrows to the procedures carrying exactly that name,
        which may be none, one, or several.

        `beamline` narrows to the procedures composed for one beamline.
        Both filters together narrow to the intersection, which is the
        only reading that lets a caller ask the question an operator
        actually has: what can this station run.

        `include_retired` adds the procedures this system no longer hands
        out. Off, a page holds active procedures alone.

        None of the three has a default. An adapter that may omit a filter
        is one a caller can silently lose a filter to, and the loss reads
        as a correct answer to a question nobody asked: every procedure in
        the facility, offered as the procedures at one beamline.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["ProcedureSummary", "ProcedureSummaryLookup", "ProcedureSummaryPage"]
