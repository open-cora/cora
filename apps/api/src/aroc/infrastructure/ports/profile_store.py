"""ProfileStore port: cross-BC R/W access to the actor_profile PII vault.

`ProfileStore` is the read / write / erase contract for the
`actor_profile` table (PII vault per the personal-data convention in docs/reference/conventions.md +
the personal-data convention in docs/reference/conventions.md). The table is owned
by the Access BC at the SQL level, but the WRITE path is shared
across BCs, `register_actor` (Access BC) AND `define_agent`
(Agent BC, via the cross-BC atomic genesis) both upsert profile
rows under the same `actor_id`. Putting the Protocol in
`aroc.infrastructure.ports` matches the pattern used by
`Authorize` (Trust BC ports the contract; every BC consumes it)
and `ClearanceLookup` (Safety BC implements, Run BC consumes).

## Why the Protocol is here, not in aroc.access

If the Protocol lived inside `aroc.access`, the Agent BC's
`define_agent` handler would still import it from there, which
is acceptable per the existing BC-import graph but creates an
ordering hazard at wire time. The handlers need ONE shared
ProfileStore instance per process so the in-memory adapter sees
writes from BOTH BC slices when `app_env=test`. Promoting the
port to the Kernel forces single-instance construction in
`make_*_kernel` and removes the "each wire function builds its
own dict" race.

## Adapters

`InMemoryProfileStore` (tests / `app_env=test`) and
`PostgresProfileStore` (production) both live in the Access BC
at `aroc.access.aggregates.actor.profile` next to the SQL the
adapter executes. The Kernel's `profile_store` field is typed
as this Protocol so the kernel-construction primitives can
stay BC-free.

## Erasure model

`scrub_and_delete` does an UPDATE-then-DELETE pass in the
caller's transaction so the dead-tuple bytes that linger until
VACUUM no longer carry PII. Same shape that `forget_actor`
relies on for atomic event + erasure.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class Profile:
    """One row in the actor_profile PII vault.

    Today carries `name` only; future PII fields (email, phone,
    ORCID, affiliation) land as additive nullable columns per
    the design notes PII vault entry. The dataclass field
    set grows with the table.
    """

    actor_id: UUID
    name: str
    created_at: datetime
    updated_at: datetime


class ProfileStore(Protocol):
    """Read / write / erase access to the actor_profile table.

    Two implementors in AROC today: `PostgresProfileStore`
    (production) and `InMemoryProfileStore` (tests /
    `app_env=test`). Both live in
    `aroc.access.aggregates.actor.profile`; the Kernel exposes
    the singleton instance under `deps.profile_store`.

    Every method is idempotent on retry per the at-least-once
    delivery convention shared with `EventStore` and
    `IdempotencyStore`.
    """

    async def upsert(
        self,
        *,
        actor_id: UUID,
        name: str,
        created_at: datetime,
    ) -> None:
        """Insert a new profile row or update the name on an existing row.

        Used by `register_actor` (Access BC) and `define_agent`
        (Agent BC) slice handlers. Idempotent on the actor_id PK:
        retrying the same upsert after a partial failure replays
        cleanly.
        """
        ...

    async def get(self, actor_id: UUID) -> Profile | None:
        """Fetch a profile row by actor_id; returns None when absent
        (erased or never-registered)."""
        ...

    async def get_many(self, actor_ids: Sequence[UUID]) -> dict[UUID, Profile]:
        """Bulk fetch profiles by actor_id; missing actor_ids are absent
        from the result."""
        ...

    async def scrub_and_delete(self, conn: object, actor_id: UUID) -> None:
        """Scrub PII columns then DELETE the row, IN the caller's transaction.

        Used by `forget_actor` so the erasure is atomic with the
        `ActorProfileForgotten` event append. `conn` is the asyncpg
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
