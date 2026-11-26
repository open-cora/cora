"""Read setup summaries out of the projection table.

The deployment half of the `SetupSummaryLookup` port, and the operation
lookup's sibling. Same keyset ordering on `(created_at, setup_id)`, same
reason for the id being in the sort key rather than only in the output,
same read-one-row-past-the-page trick for deciding whether a next page
exists. Read `postgres_execution_summary_lookup.py` for the reasoning
behind all three; it is written out there and not repeated here.

The three filters are equalities, ANDed, each written as a null guard over
the same query. The key lookup is the same three equalities with none of
them optional, ordered the other way, oldest first, and cut at one row, so
that a key a race let two setups under returns the first of them. The
`(beamline, operation_id, name)` index serves both.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from typing import Any
from uuid import UUID

import asyncpg

from keeper.execution.aggregates.setup.state import SetupBeamline, SetupName
from keeper.execution.aggregates.setup.summary import SetupSummary, SetupSummaryPage
from keeper.execution.projections.setup_summary import PROJECTION_NAME
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor

_COLUMNS = "setup_id, beamline, operation_id, name, revision, created_at, revised_at"

_SELECT_SQL = f"""
SELECT {_COLUMNS}
FROM {PROJECTION_NAME}
WHERE ($1::text IS NULL OR beamline = $1)
  AND ($2::uuid IS NULL OR operation_id = $2)
  AND ($3::text IS NULL OR name = $3)
  AND ($4::timestamptz IS NULL OR (created_at, setup_id) < ($4, $5))
ORDER BY created_at DESC, setup_id DESC
LIMIT $6
"""

_FIND_SQL = f"""
SELECT {_COLUMNS}
FROM {PROJECTION_NAME}
WHERE beamline = $1 AND operation_id = $2 AND name = $3
ORDER BY created_at, setup_id
LIMIT 1
"""


class PostgresSetupSummaryLookup:
    """Postgres-backed implementation of the `SetupSummaryLookup` port."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def list_setups(
        self,
        *,
        beamline: SetupBeamline | None,
        operation_id: UUID | None,
        name: SetupName | None,
        limit: int,
        cursor: str | None,
    ) -> SetupSummaryPage:
        """Return one page of setups, newest first."""
        after = decode_cursor(cursor) if cursor is not None else None
        rows = await self._pool.fetch(
            _SELECT_SQL,
            beamline.value if beamline is not None else None,
            operation_id,
            name.value if name is not None else None,
            after[0] if after is not None else None,
            after[1] if after is not None else None,
            limit + 1,
        )

        has_more = len(rows) > limit
        items = [_to_summary(row) for row in rows[:limit]]
        next_cursor = (
            encode_cursor(created_at=items[-1].created_at, item_id=items[-1].setup_id)
            if has_more and items
            else None
        )
        return SetupSummaryPage(items=items, next_cursor=next_cursor)

    async def find_setup(
        self,
        *,
        beamline: SetupBeamline,
        operation_id: UUID,
        name: SetupName,
    ) -> SetupSummary | None:
        """Return the setup holding this key, the first defined if two do."""
        row = await self._pool.fetchrow(_FIND_SQL, beamline.value, operation_id, name.value)
        return _to_summary(row) if row is not None else None


def _to_summary(row: Any) -> SetupSummary:
    return SetupSummary(
        setup_id=row["setup_id"],
        beamline=SetupBeamline(row["beamline"]),
        operation_id=row["operation_id"],
        name=SetupName(row["name"]),
        revision=row["revision"],
        created_at=row["created_at"],
        revised_at=row["revised_at"],
    )


__all__ = ["PostgresSetupSummaryLookup"]
