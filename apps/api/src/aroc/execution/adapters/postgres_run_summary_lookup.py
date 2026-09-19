"""Read run summaries out of the projection table.

The deployment half of the `RunSummaryLookup` port. One SELECT against
`proj_execution_run_summary`, which a background worker keeps in step with
the run streams.

## Why the ordering is a pair and not a timestamp

Rows come back newest first by `(created_at, run_id)`, and the id is in
the sort key rather than only in the output. Two runs reported at the same
instant, which a backfill produces routinely, would otherwise have no
defined order between them, and a page boundary landing in the middle of
such a tie either repeats a row or skips one. The id breaks every tie the
same way on every page.

That pair is also what the cursor carries, which is why the comparison
below is a row comparison, `(created_at, run_id) < (...)`, rather than
two ANDed inequalities. Postgres can use the index for the row form.

## Reading one row past the page

The query asks for `limit + 1` rows and the extra one is not returned. Its
presence is the whole answer to "is there a next page", and asking that
way costs one row rather than a second COUNT query over the table. The
cursor handed back is the sort key of the LAST row actually returned, so
the next page resumes exactly where this one stopped.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import asyncpg

from aroc.execution.aggregates.run.state import RunStatus
from aroc.execution.aggregates.run.summary import RunSummary, RunSummaryPage
from aroc.execution.projections.run_summary import PROJECTION_NAME
from aroc.infrastructure.projection.cursor import decode_cursor, encode_cursor
from aroc.shared.identifier import Identifier

_SELECT_SQL = f"""
SELECT run_id, plan_id, external_ref_scheme, external_ref_value,
       status, created_at, updated_at
FROM {PROJECTION_NAME}
WHERE ($1::text IS NULL OR external_ref_scheme = $1)
  AND ($2::text IS NULL OR external_ref_value = $2)
  AND ($3::timestamptz IS NULL OR (created_at, run_id) < ($3, $4))
ORDER BY created_at DESC, run_id DESC
LIMIT $5
"""


class PostgresRunSummaryLookup:
    """Postgres-backed implementation of the `RunSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_runs(
        self,
        *,
        external_ref: Identifier | None,
        limit: int,
        cursor: str | None,
    ) -> RunSummaryPage:
        """Return one page of runs, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            external_ref.scheme if external_ref is not None else None,
            external_ref.value if external_ref is not None else None,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].run_id)
            if has_more and items
            else None
        )
        return RunSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> RunSummary:
    return RunSummary(
        run_id=row["run_id"],
        plan_id=row["plan_id"],
        external_ref=Identifier(
            scheme=row["external_ref_scheme"],
            value=row["external_ref_value"],
        ),
        status=RunStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


__all__ = ["PostgresRunSummaryLookup"]
