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
to be called successfully in an execution of the surface, and those executions boot
the application with in-memory adapters and no database at all. A tool
that refuses because there is no pool fails that execution; one that answers
"no executions" while executions exist is worse, because it is wrong rather than
unavailable.

So this is a port with two honest implementations, which is what the run
summary next door already is. In a deployment it reads the projection.
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

from aroc.execution.aggregates.execution.state import ExecutionStatus


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
    here can tell either from something merely slow, which is the limit
    docs/reference/conducting.md names rather than papers over.
    """

    execution_id: UUID
    procedure_id: UUID
    procedure_name: str
    step_count: int
    reported_count: int
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
        limit: int,
        cursor: str | None,
    ) -> ExecutionSummaryPage:
        """Return one page of executions, newest first.

        `procedure_id` narrows to the executions dispatched for that
        procedure, which may be none, one, or many: a routine composed
        once is walked every time it runs.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["ExecutionSummary", "ExecutionSummaryLookup", "ExecutionSummaryPage"]
