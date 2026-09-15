"""ProfileStore port: cross-BC read, write, and erase for the PII vault.

`ProfileStore` is the contract for the `principal_profile` table, the separate
mutable home personal data lives in so that events can stay immutable and
personal data can still be deleted. See the personal-data convention in
docs/reference/conventions.md for the pattern; this is its seam.

## Why the Protocol is here rather than in a bounded context

Several BCs may register a principal, and every one of them needs the SAME
store instance per process, or the in-memory adapter under `app_env=test`
sees writes from one slice and not another. A Protocol owned by one BC would
still be importable by the others, but nothing would force single-instance
construction, and each `wire_<bc>` would build its own.

Putting the port here and the instance on the `Kernel` makes single
construction structural rather than conventional.

## Erasure model

`scrub_and_delete` does an UPDATE-then-DELETE pass inside the CALLER's
transaction, so the dead-tuple bytes that linger until VACUUM no longer carry
personal data, and so the erasure commits atomically with the audit event that
records it. A delete alone would leave the old row image readable on disk; a
delete in its own transaction would let the two halves diverge.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class Profile:
    """One row in the principal_profile PII vault.

    Today carries `name` only; future PII fields (email, phone,
    ORCID, affiliation) land as additive nullable columns per
    the design notes PII vault entry. The dataclass field
    set grows with the table.
    """

    principal_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class ProfileStore(Protocol):
    """Read / write / erase access to the principal_profile table.

    Two implementors in AROC today: `PostgresProfileStore`
    (production) and `InMemoryProfileStore` (tests /
    `app_env=test`). Both live in
    a BC that owns principals; the Kernel exposes
    the singleton instance under `deps.profile_store`.

    Every method is idempotent on retry per the at-least-once
    delivery convention shared with `EventStore` and
    `IdempotencyStore`.
    """

    async def upsert(
        self,
        *,
        principal_id: UUID,
        name: str,
        created_at: datetime,
    ) -> None:
        """Insert a new profile row or update the name on an existing row.

        Used by any slice that registers a principal
        (Agent BC) slice handlers. Idempotent on the principal_id PK:
        retrying the same upsert after a partial failure replays
        cleanly.
        """
        ...

    async def get(self, principal_id: UUID) -> Profile | None:
        """Fetch a profile row by principal_id; returns None when absent
        (erased or never-registered)."""
        ...

    async def get_many(self, principal_ids: Sequence[UUID]) -> dict[UUID, Profile]:
        """Bulk fetch profiles by principal_id; missing principal_ids are absent
        from the result."""
        ...

    async def scrub_and_delete(self, conn: object, principal_id: UUID) -> None:
        """Scrub PII columns then DELETE the row, IN the caller's transaction.

        Used by an erasure slice so the deletion is atomic with the
        `<Subject>ProfileForgotten` audit-event append. `conn` is the asyncpg
        `Connection` (or pool-acquired `PoolConnectionProxy`)
        inside the open transaction; typed as `object` so the
        Protocol stays asyncpg-agnostic, matching the
        `EventStore.append_streams(conn=...)` convention.
        InMemoryProfileStore ignores the parameter (no transaction).

        Scrub-then-DELETE shape (UPDATE name='' before DELETE)
        ensures the dead-tuple bytes (linger until VACUUM
        rewrites the page) no longer contain PII. Postgres-canonical
        WAL/dead-tuple PII cleanup pattern.

        Idempotent on missing row (rowcount = 0 from both
        statements).
        """
        ...


__all__ = [
    "Profile",
    "ProfileStore",
]
