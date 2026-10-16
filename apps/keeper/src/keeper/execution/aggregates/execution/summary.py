"""One row per execution, and the port that reads those rows.

The other read path. `read.py` rebuilds one execution by replaying its
stream, which is the right trade for a question that names an execution. This
is for the question that does not: which executions were dispatched for this
procedure, and how far did each get. Folding cannot answer it, because
folding needs to know which stream to fold and that is exactly what is
being asked.

## Why a port rather than a pool

The rows live in `proj_execution_execution_summary`, a table a background
worker maintains. The MCP surface contract requires every published tool
to be called successfully in a walk of the surface, and those walks boot
the application with in-memory adapters and no database at all. A tool
that refuses because there is no pool fails that execution; one that answers
"no executions" while executions exist is worse, because it is wrong rather than
unavailable.

So this is a port with two honest implementations, which is what every
summary port in this tree is. In a deployment it reads the projection.
In memory it folds every execution stream, which is the expensive thing the
table exists to avoid and is free when the whole store is a dictionary.

## What a summary leaves out

The steps. They are the largest thing an execution carries, up to a thousand
of them, and a page of fifty executions would be almost entirely steps. What
a list needs instead is how far the execution got, which is two integers, and
a caller wanting the steps has the execution id and one more call.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.execution.state import ExecutionBeamline, ExecutionStatus


@dataclass(frozen=True)
class ExecutionSummary:
    """An execution as a list shows it.

    `created_at` is when the execution was dispatched and `updated_at` when
    the last thing known about it was reported to have happened. Both are
    the domain time a caller supplied, not the moment a row was written,
    so both can sit in the past.

    `reported_count` against `step_count` is how far it got, and `status`
    says what is happening to it. Together they separate the cases a
    reader cares about: dispatched and untouched, claimed but not yet
    started, running, closed having reported everything, and closed
    having not.

    `DISPATCHED` with an old `created_at` is the row worth looking at. It
    says nothing ever took the execution up, which is a different failure from
    an execution whose driver died partway: that one shows as `RUNNING` with
    `reported_count` short of `step_count`, and stays that way. Nothing
    here can tell either from something merely slow, which is a limit to
    name rather than paper over.

    `routines` is what the execution needs an engine for, and it is on
    the listing rather than only in the filter below because it is the
    only thing that makes the row this change introduces readable: an
    execution dispatched to a beamline where nothing runs its routines
    sits at `DISPATCHED` and is returned to no conductor at all. Without
    this column that reads as a quiet day.

    Empty means no step runs anything, so anything may take it up.
    """

    execution_id: UUID
    procedure_id: UUID
    procedure_name: str
    beamline: ExecutionBeamline
    step_count: int
    reported_count: int
    routines: tuple[str, ...]
    status: ExecutionStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ExecutionSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. It is opaque on
    purpose: it encodes the sort key of the final row, and a caller that
    takes it apart is depending on an ordering this is free to change.
    """

    items: list[ExecutionSummary]
    next_cursor: str | None


class ExecutionSummaryLookup(Protocol):
    """Read executions by something other than their id.

    Named `Lookup` because that is the shape this repository declares for
    a read port, in `test_port_naming_conventions.py`.
    """

    async def list_executions(
        self,
        *,
        procedure_id: UUID | None,
        beamline: ExecutionBeamline | None,
        status: ExecutionStatus | None,
        runs: frozenset[str] | None,
        limit: int,
        cursor: str | None,
    ) -> ExecutionSummaryPage:
        """Return one page of executions, newest first.

        `procedure_id` narrows to the executions dispatched for that
        procedure, which may be none, one, or many: a routine composed
        once is walked every time it runs.

        `beamline` and `status` are the work intake's pair, and they are
        two parameters rather than one because each is useful alone. A
        conductor asks for both at once, `2-bm` and `Dispatched`, which
        is the only question this read model is expected to answer
        continuously; an operator asks for a beamline and every status,
        or for everything still dispatched anywhere.

        `runs` is the work intake's third narrowing, and it is a subset
        test rather than an overlap one: a row is returned when every
        routine it needs is in the set given, because a conductor that
        can run some of an execution's steps can still only claim it
        once and would refuse the rest. The direction is what makes the
        two empty cases come out right. A row needing nothing is
        returned to every caller including one that gave the empty set,
        and a caller that runs nothing is offered only rows that need
        nothing. Neither is a special case in an adapter; both fall out
        of the subset.

        `None` is not the empty set here, and the difference matters more
        than it usually does. `None` means do not narrow, which is what
        a person browsing wants; the empty set means a caller with no
        engine, which is a real and much smaller answer.

        All four narrow independently, and none of them is required.
        Every combination is a filter over the same page, so an adapter
        that implemented them as anything but an AND would answer a
        question nobody asked.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["ExecutionSummary", "ExecutionSummaryLookup", "ExecutionSummaryPage"]
