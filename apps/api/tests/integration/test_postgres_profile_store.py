"""The personal-data vault, against a real Postgres.

Nothing exercised this adapter until now, which mattered the moment the
table was renamed: the DDL lives in a migration and the SQL lives in the
adapter, they are written in the same language but in different files, and
a disagreement between them is invisible to the type checker, to the linter
and to every other test in this suite. It surfaces as a runtime error on
the first write, in whatever environment reaches it first.

Three properties are checked here rather than against a fake, because all
three are properties of the database:

  - the adapter's table and column names match the ones the migration made
  - the upsert really is idempotent on the key, via the ON CONFLICT clause
  - erasure runs inside the CALLER's transaction, so a rollback takes the
    deletion with it

The third is the one worth having. Erasure is supposed to commit atomically
with the audit event that records it, and an adapter that quietly opened its
own transaction would pass any test that did not roll one back.
"""

# asyncpg's pool.acquire() and the proxy it yields are untyped, so every
# `async with pool.acquire()` leaks Any into this file. All three rules below
# are load-bearing here: four errors each, from `acquire` and `transaction`
# (member), the bound `conn` (variable), and `conn` passed on (argument).
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from datetime import UTC, datetime
from uuid import uuid4

import asyncpg
import pytest

from aroc.infrastructure.adapters.postgres_profile_store import PostgresProfileStore

pytestmark = [pytest.mark.integration]

_WHEN = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


async def test_a_written_profile_reads_back_with_the_name_it_was_given(
    db_pool: asyncpg.Pool,
) -> None:
    store = PostgresProfileStore(db_pool)
    actor_id = uuid4()
    await store.upsert(actor_id=actor_id, name="Ada Lovelace", created_at=_WHEN)

    found = await store.get(actor_id)
    assert found is not None
    assert found.actor_id == actor_id
    assert found.name == "Ada Lovelace"


async def test_get_returns_none_for_an_actor_with_no_profile_row(
    db_pool: asyncpg.Pool,
) -> None:
    assert await PostgresProfileStore(db_pool).get(uuid4()) is None


async def test_a_second_upsert_replaces_the_name_rather_than_failing(
    db_pool: asyncpg.Pool,
) -> None:
    """The key is the actor, so re-registering a name is an update."""
    store = PostgresProfileStore(db_pool)
    actor_id = uuid4()
    await store.upsert(actor_id=actor_id, name="Ada Lovelace", created_at=_WHEN)
    await store.upsert(actor_id=actor_id, name="Ada King", created_at=_WHEN)

    found = await store.get(actor_id)
    assert found is not None
    assert found.name == "Ada King"


async def test_get_many_returns_only_the_actors_that_have_a_row(
    db_pool: asyncpg.Pool,
) -> None:
    store = PostgresProfileStore(db_pool)
    present, absent = uuid4(), uuid4()
    await store.upsert(actor_id=present, name="Ada Lovelace", created_at=_WHEN)

    found = await store.get_many([present, absent])
    assert set(found) == {present}


async def test_get_many_returns_nothing_when_asked_for_nothing(
    db_pool: asyncpg.Pool,
) -> None:
    """The empty-input short circuit, which never reaches the database."""
    assert await PostgresProfileStore(db_pool).get_many([]) == {}


async def test_erasure_removes_the_row_when_its_transaction_commits(
    db_pool: asyncpg.Pool,
) -> None:
    store = PostgresProfileStore(db_pool)
    actor_id = uuid4()
    await store.upsert(actor_id=actor_id, name="Ada Lovelace", created_at=_WHEN)

    async with db_pool.acquire() as conn, conn.transaction():
        await store.scrub_and_delete(conn, actor_id)

    assert await store.get(actor_id) is None


async def test_erasure_is_undone_when_the_callers_transaction_rolls_back(
    db_pool: asyncpg.Pool,
) -> None:
    """Erasure must join the caller's transaction, not open its own.

    An adapter that took its own connection would delete the row here and
    leave it deleted, so the audit event and the deletion could diverge.
    """
    store = PostgresProfileStore(db_pool)
    actor_id = uuid4()
    await store.upsert(actor_id=actor_id, name="Ada Lovelace", created_at=_WHEN)

    rollback = RuntimeError("the audit append failed")
    with pytest.raises(RuntimeError, match="the audit append failed"):
        async with db_pool.acquire() as conn, conn.transaction():
            await store.scrub_and_delete(conn, actor_id)
            raise rollback

    still_there = await store.get(actor_id)
    assert still_there is not None
    assert still_there.name == "Ada Lovelace"


async def test_erasure_of_an_absent_row_is_not_an_error(
    db_pool: asyncpg.Pool,
) -> None:
    """A replayed erasure request must not fail the second time."""
    store = PostgresProfileStore(db_pool)
    async with db_pool.acquire() as conn, conn.transaction():
        await store.scrub_and_delete(conn, uuid4())
