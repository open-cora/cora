"""One row per run, and the port that reads those rows.

The other read path. `read.py` rebuilds one run by replaying its stream,
which is the right trade for a question that names a run. This is for the
questions that do not: which run carries this external reference, and what
has run lately. Neither can be answered by folding, because folding needs
to know which stream to fold, and both of these are asking exactly that.

## Why a port rather than a pool

The rows live in `proj_execution_run_summary`, a table a background worker
maintains. A handler could read that table directly through the kernel's
connection pool, which is what the read-side notes in
docs/reference/patterns.md describe.

It does not work here, and the test suite is what says so. The MCP surface
contract requires every published tool to be called successfully in a walk,
and those walks boot the application with in-memory adapters and no
database at all. A tool that refuses because there is no pool fails the
walk; one that answers "no runs" while runs exist is worse, because it is
wrong rather than unavailable.

So this is a port with two honest implementations, which is what every
other thing this application reads from already is. In a deployment it
reads the projection. In memory it folds every run stream, which is the
expensive thing the table exists to avoid and is free when the whole store
is a dictionary.

## What a summary leaves out

`parameters` is not here. It is unbounded, it is the largest field a run
carries, and a page of fifty rows would be mostly parameters. A caller that
wants them has the run id and one more call.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from aroc.execution.aggregates.run.state import RunStatus
from aroc.shared.identifier import Identifier


@dataclass(frozen=True)
class RunSummary:
    """A run as a list shows it.

    `created_at` is when the run was reported to have started and
    `updated_at` when the last thing known about it was reported to have
    happened. Both are the domain time a caller supplied, not the moment
    a row was written, so both can sit in the past and, if two reporters
    disagree, `updated_at` can move backwards. The event log is where the
    write times live.

    A run that has ended still has an `updated_at` and no separate ending
    time. `status` names which ending it was, and a column per ending
    would say the same thing four more times.
    """

    run_id: UUID
    plan_id: UUID
    external_ref: Identifier
    status: RunStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class RunSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. It is opaque on
    purpose: it encodes the sort key of the final row, and a caller that
    takes it apart is depending on an ordering this is free to change.
    """

    items: list[RunSummary]
    next_cursor: str | None


class RunSummaryLookup(Protocol):
    """Read runs by something other than their id.

    Named `Lookup` because that is the shape this repository declares for
    a read port, in `test_port_naming_conventions.py`. The rule is written
    there for a cross-context read; this one is Execution's own, and
    borrowing the vocabulary beats inventing a second word for the same
    idea.
    """

    async def list_runs(
        self,
        *,
        external_ref: Identifier | None,
        limit: int,
        cursor: str | None,
    ) -> RunSummaryPage:
        """Return one page of runs, newest first.

        `external_ref` narrows to the runs carrying that exact pair, which
        is normally none or one and is deliberately not guaranteed to be
        either: nothing stops two records of one engine run, so a caller
        asking this question has to be able to see both.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["RunSummary", "RunSummaryLookup", "RunSummaryPage"]
