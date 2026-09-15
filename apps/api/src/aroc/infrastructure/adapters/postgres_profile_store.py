"""Postgres `ProfileStore` adapter: asyncpg-backed principal_profile R/W.

Sibling to `aroc.infrastructure.adapters.postgres_event_store` and
`aroc.infrastructure.adapters.postgres_idempotency_store`. The adapter lives in
infrastructure (not in `aroc.access`) so the kernel-construction
primitives in `aroc.infrastructure.deps` can wire it without
importing any BC, matches the EventStore + IdempotencyStore
placement convention.

## Erasure semantics

`scrub_and_delete` does an UPDATE-then-DELETE pass in the
caller's transaction. The scrub UPDATE writes empty values
before DELETE so the dead-tuple bytes that linger until VACUUM
no longer carry PII. Postgres-canonical WAL/dead-tuple PII
cleanup pattern; consumed by whichever slice implements erasure
slice.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# (asyncpg's typed-Pool/Connection narrows poorly in strict mode; matches the
# convention in aroc/infrastructure/postgres/idempotency.py for the same reason.)

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

import asyncpg

from aroc.infrastructure.ports.profile_store import Profile

_UPSERT_SQL = """
INSERT INTO principal_profile (principal_id, name, created_at, updated_at)
VALUES ($1, $2, $3, $3)
ON CONFLICT (principal_id) DO UPDATE
    SET name = EXCLUDED.name,
        updated_at = now()
"""

_GET_SQL = """
SELECT principal_id, name, created_at, updated_at
FROM principal_profile
WHERE principal_id = $1
"""

_GET_MANY_SQL = """
SELECT principal_id, name, created_at, updated_at
FROM principal_profile
WHERE principal_id = ANY($1::uuid[])
"""

_SCRUB_SQL = "UPDATE principal_profile SET name = '' WHERE principal_id = $1"

_DELETE_SQL = "DELETE FROM principal_profile WHERE principal_id = $1"


def _row_to_profile(row: Any) -> Profile:
    # `row: Any` matches the convention used by every list-query handler;
    # asyncpg's Record stub doesn't narrow column types, so we coerce here.
    return Profile(
        principal_id=row["principal_id"],
        name=str(row["name"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class PostgresProfileStore:
    """asyncpg-backed `ProfileStore` implementation.

    All four methods are idempotent on retry:
      - upsert: ON CONFLICT DO UPDATE (rename-on-retry semantics).
      - get / get_many: pure reads.
      - scrub_and_delete: rowcount = 0 on missing row (no error).
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert(
        self,
        *,
        principal_id: UUID,
        name: str,
        created_at: datetime,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_UPSERT_SQL, principal_id, name, created_at)

    async def get(self, principal_id: UUID) -> Profile | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(_GET_SQL, principal_id)
        if row is None:
            return None
        return _row_to_profile(row)

    async def get_many(self, principal_ids: Sequence[UUID]) -> dict[UUID, Profile]:
        if not principal_ids:
            return {}
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(_GET_MANY_SQL, list(principal_ids))
        return {row["principal_id"]: _row_to_profile(row) for row in rows}

    async def scrub_and_delete(self, conn: object, principal_id: UUID) -> None:
        # Scrub first (UPDATE name = '') so the dead tuple bytes that
        # linger until VACUUM no longer contain PII. Then DELETE marks
        # the scrubbed version dead. Both statements idempotent on
        # missing row (rowcount = 0).
        #
        # `conn` is typed as `object` on the Protocol; the adapter
        # narrows at runtime by calling `conn.execute(...)`, which both
        # asyncpg.Connection and PoolConnectionProxy expose with the
        # same signature.
        pg_conn: asyncpg.Connection = conn  # type: ignore[assignment]
        await pg_conn.execute(_SCRUB_SQL, principal_id)
        await pg_conn.execute(_DELETE_SQL, principal_id)


__all__ = ["PostgresProfileStore"]
