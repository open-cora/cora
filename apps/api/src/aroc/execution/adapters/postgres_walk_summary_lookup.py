"""Read walk summaries out of the projection table.

The deployment half of the `WalkSummaryLookup` port. One SELECT against
`proj_execution_walk_summary`, which a background worker keeps in step
with the walk streams.

## Why the ordering is a pair and not a timestamp

Rows come back newest first by `(created_at, walk_id)`, and the id is in
the sort key rather than only in the output. Two walks reported at the
same instant would otherwise have no defined order between them, and a
page boundary landing in the middle of such a tie either repeats a row
or skips one. The id breaks every tie the same way on every page.

That pair is also what the cursor carries, which is why the comparison
below is a row comparison rather than two ANDed inequalities. Postgres
can use the index for the row form.

## Reading one row past the page

The query asks for `limit + 1` rows and the extra one is not returned.
Its presence is the whole answer to "is there a next page", and asking
that way costs one row rather than a second COUNT over the table.

## The count comes out of the array

`reported_indices` holds the steps reported, because a counter cannot be
made idempotent under at-least-once delivery. The port exposes a number,
so the cardinality is taken in SQL rather than by shipping the array to
Python and measuring it here: a walk may hold a thousand indices and
none of them is wanted.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import asyncpg

from aroc.execution.aggregates.walk.summary import WalkSummary, WalkSummaryPage
from aroc.execution.projections.walk_summary import PROJECTION_NAME
from aroc.infrastructure.projection.cursor import decode_cursor, encode_cursor
from aroc.shared.identifier import Identifier

_SELECT_SQL = f"""
SELECT walk_id, reference_scheme, reference_value, procedure_name,
       step_count, cardinality(reported_indices) AS reported_count,
       ended, created_at, updated_at
FROM {PROJECTION_NAME}
WHERE ($1::text IS NULL OR reference_scheme = $1)
  AND ($2::text IS NULL OR reference_value = $2)
  AND ($3::timestamptz IS NULL OR (created_at, walk_id) < ($3, $4))
ORDER BY created_at DESC, walk_id DESC
LIMIT $5
"""


class PostgresWalkSummaryLookup:
    """Postgres-backed implementation of the `WalkSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_walks(
        self,
        *,
        reference: Identifier | None,
        limit: int,
        cursor: str | None,
    ) -> WalkSummaryPage:
        """Return one page of walks, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            reference.scheme if reference is not None else None,
            reference.value if reference is not None else None,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].walk_id)
            if has_more and items
            else None
        )
        return WalkSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> WalkSummary:
    return WalkSummary(
        walk_id=row["walk_id"],
        reference=Identifier(
            scheme=row["reference_scheme"],
            value=row["reference_value"],
        ),
        procedure_name=row["procedure_name"],
        step_count=row["step_count"],
        reported_count=row["reported_count"],
        ended=row["ended"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = ["PostgresWalkSummaryLookup"]
