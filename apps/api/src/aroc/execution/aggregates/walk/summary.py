"""One row per walk, and the port that reads those rows.

The other read path. `read.py` rebuilds one walk by replaying its
stream, which is the right trade for a question that names a walk. This
is for the question that does not: which walk carries this reference.
Folding cannot answer it, because folding needs to know which stream to
fold and that is exactly what is being asked.

## Why a port rather than a pool

The rows live in `proj_execution_walk_summary`, a table a background
worker maintains. The MCP surface contract requires every published tool
to be called successfully in a walk of the surface, and those walks boot
the application with in-memory adapters and no database at all. A tool
that refuses because there is no pool fails that walk; one that answers
"no walks" while walks exist is worse, because it is wrong rather than
unavailable.

So this is a port with two honest implementations, which is what the run
summary next door already is. In a deployment it reads the projection.
In memory it folds every walk stream, which is the expensive thing the
table exists to avoid and is free when the whole store is a dictionary.

## What a summary leaves out

The steps. They are the largest thing a walk carries, up to a thousand
of them, and a page of fifty walks would be almost entirely steps. What
a list needs instead is how far the walk got, which is two integers, and
a caller wanting the steps has the walk id and one more call.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from aroc.shared.identifier import Identifier


@dataclass(frozen=True)
class WalkSummary:
    """A walk as a list shows it.

    `created_at` is when the walk was reported to have begun and
    `updated_at` when the last thing known about it was reported to have
    happened. Both are the domain time a caller supplied, not the moment
    a row was written, so both can sit in the past.

    `reported_count` against `step_count` is how far it got, and `ended`
    says whether anything more is coming. Together they separate the
    three cases a reader cares about: still running, closed having
    reported everything, and closed having not.

    A walk whose driver died shows as not ended with `reported_count`
    short of `step_count`, and stays that way. Nothing here can tell it
    from a walk that is merely slow, which is the limit
    docs/reference/conducting.md names rather than papers over.
    """

    walk_id: UUID
    reference: Identifier
    procedure_name: str
    step_count: int
    reported_count: int
    ended: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class WalkSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    `next_cursor` is None when this is the last page. It is opaque on
    purpose: it encodes the sort key of the final row, and a caller that
    takes it apart is depending on an ordering this is free to change.
    """

    items: list[WalkSummary]
    next_cursor: str | None


class WalkSummaryLookup(Protocol):
    """Read walks by something other than their id.

    Named `Lookup` because that is the shape this repository declares for
    a read port, in `test_port_naming_conventions.py`.
    """

    async def list_walks(
        self,
        *,
        reference: Identifier | None,
        limit: int,
        cursor: str | None,
    ) -> WalkSummaryPage:
        """Return one page of walks, newest first.

        `reference` narrows to the walks carrying that exact pair, which
        is normally none or one and is deliberately not guaranteed to be
        either: nothing stops two records of one walk, so a caller
        asking this question has to be able to see both.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...


__all__ = ["WalkSummary", "WalkSummaryLookup", "WalkSummaryPage"]
