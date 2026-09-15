"""In-memory `ProfileStore` adapter for tests and `app_env=test`.

Mirrors `aroc.infrastructure.adapters.in_memory_event_store` /
`aroc.infrastructure.adapters.in_memory_idempotency_store`: pure-dict implementor of
the `ProfileStore` port, used by every Kernel built with
`make_inmemory_kernel`. One instance lives on `Kernel.profile_store`
so Access BC (`register_actor`) and Agent BC (`define_agent`)
slice handlers see the same writes through a single shared dict.

Postgres semantics preserved: on insert, `updated_at = created_at`;
on update, `updated_at = datetime.now(tz=UTC)`. The `conn` argument
on `scrub_and_delete` is ignored (no transaction in-memory); the
contract is preserved at the type level so unit tests and
production code share one Protocol.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from aroc.infrastructure.ports.profile_store import Profile


class InMemoryProfileStore:
    """Process-local dict adapter for `ProfileStore`."""

    def __init__(self) -> None:
        self._rows: dict[UUID, Profile] = {}

    async def upsert(
        self,
        *,
        actor_id: UUID,
        name: str,
        created_at: datetime,
    ) -> None:
        existing = self._rows.get(actor_id)
        if existing is None:
            self._rows[actor_id] = Profile(
                actor_id=actor_id,
                name=name,
                created_at=created_at,
                updated_at=created_at,
            )
        else:
            self._rows[actor_id] = Profile(
                actor_id=actor_id,
                name=name,
                created_at=existing.created_at,
                updated_at=datetime.now(tz=UTC),
            )

    async def get(self, actor_id: UUID) -> Profile | None:
        return self._rows.get(actor_id)

    async def get_many(self, actor_ids: Sequence[UUID]) -> dict[UUID, Profile]:
        return {aid: self._rows[aid] for aid in actor_ids if aid in self._rows}

    async def scrub_and_delete(self, conn: object, actor_id: UUID) -> None:
        _ = conn  # in-memory: no transaction; contract preserved at type level
        self._rows.pop(actor_id, None)


__all__ = ["InMemoryProfileStore"]
