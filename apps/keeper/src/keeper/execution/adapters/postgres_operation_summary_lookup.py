"""Read operation summaries out of the projection table.

The deployment half of the `OperationSummaryLookup` port, and the execution
lookup's sibling. Same keyset ordering on `(created_at, operation_id)`, same
reason for the id being in the sort key rather than only in the output,
same read-one-row-past-the-page trick for deciding whether a next page
exists. Read `postgres_execution_summary_lookup.py` for the reasoning
behind all three; it is written out there and not repeated here.

One difference. Filtering by name is an equality on a column that is not
unique and is not meant to be, so this is the query most likely to return
two rows where a caller expected one. Nothing here smooths that over.

The retired switch is a third parameter rather than a status filter: off,
the query keeps the active rows alone, and on it keeps every row. The
status is spelled from the enum rather than written into the SQL, so the
word the projection writes and the word this compares against are one.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any

import asyncpg

from keeper.execution.aggregates.operation.state import OperationName, OperationStatus
from keeper.execution.aggregates.operation.summary import OperationSummary, OperationSummaryPage
from keeper.execution.projections.operation_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_SELECT_SQL = f"""
SELECT operation_id, name, status, drives_devices, created_at
FROM {PROJECTION_NAME}
WHERE ($1::text IS NULL OR name = $1)
  AND ($2::boolean OR status = $3)
  AND ($4::timestamptz IS NULL OR (created_at, operation_id) < ($4, $5))
ORDER BY created_at DESC, operation_id DESC
LIMIT $6
"""


class PostgresOperationSummaryLookup:
    """Postgres-backed implementation of the `OperationSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_operations(
        self,
        *,
        name: OperationName | None,
        include_retired: bool,
        limit: int,
        cursor: str | None,
    ) -> OperationSummaryPage:
        """Return one page of operations, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            name.value if name is not None else None,
            include_retired,
            OperationStatus.ACTIVE.value,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].operation_id)
            if has_more and items
            else None
        )
        return OperationSummaryPage(items=items, next_cursor=next_cursor)


def _to_summary(row: Any) -> OperationSummary:
    return OperationSummary(
        operation_id=row["operation_id"],
        name=OperationName(row["name"]),
        status=OperationStatus(row["status"]),
        drives_devices=row["drives_devices"],
        created_at=row["created_at"],
    )


__all__ = ["PostgresOperationSummaryLookup"]
