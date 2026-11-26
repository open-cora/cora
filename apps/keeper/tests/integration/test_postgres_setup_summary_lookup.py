"""The setup projection and its two queries, against a real Postgres.

The other side of the setup-summary contract. The execution file beside
this one carries the shared reasoning about draining, replay and lag; what
is here is the setup's own: an insert and then any number of updates, each
writing the number its event carries, so the replay checks below are the
ones that matter most.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution.adapters.postgres_setup_summary_lookup import PostgresSetupSummaryLookup
from keeper.execution.aggregates.setup.state import SetupBeamline, SetupName
from keeper.execution.projections.setup_summary import SetupSummaryProjection
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.projection.worker import advance_subscriber_once
from tests._port_contracts._writers import EventStoreSetupWriter
from tests._port_contracts.setup_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]

_WHEN = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)


class _DrainingSetupWriter:
    """Append setup events, then let the projection catch up."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreSetupWriter(PostgresEventStore(pool))
        self._projection = SetupSummaryProjection()

    async def define(
        self,
        *,
        setup_id: UUID,
        beamline: SetupBeamline,
        operation_id: UUID,
        name: SetupName,
        at: datetime,
    ) -> None:
        await self._writer.define(
            setup_id=setup_id, beamline=beamline, operation_id=operation_id, name=name, at=at
        )
        await self._drain()

    async def revise(self, *, setup_id: UUID, at: datetime) -> None:
        await self._writer.revise(setup_id=setup_id, at=at)
        await self._drain()

    async def _drain(self) -> None:
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresSetupSummaryLookup:
    return PostgresSetupSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingSetupWriter:
    return _DrainingSetupWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_setup_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresSetupSummaryLookup, writer: _DrainingSetupWriter
) -> None:
    await check(lookup, writer)


async def test_the_migration_seeded_the_bookmark_this_projection_reads(
    db_pool: asyncpg.Pool,
) -> None:
    """Without the row the worker raises on its first advance, forever,
    inside its own backoff loop."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            SetupSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def _rewind_and_replay(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            SetupSummaryProjection.name,
        )
    while await advance_subscriber_once(pool, SetupSummaryProjection()):
        pass


async def test_replaying_a_batch_leaves_the_table_exactly_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresSetupSummaryLookup
) -> None:
    """Delivery is at-least-once, and the insert's ON CONFLICT is the only
    thing standing between a replay and a duplicate-key failure that would
    wedge the projection for good."""
    writer = _DrainingSetupWriter(db_pool)
    await writer.define(
        setup_id=uuid4(),
        beamline=SetupBeamline("2-bm"),
        operation_id=uuid4(),
        name=SetupName("tomo-default"),
        at=_WHEN,
    )
    first = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=10, cursor=None
    )

    await _rewind_and_replay(db_pool)

    after = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=10, cursor=None
    )
    assert after == first


async def test_replaying_a_batch_that_holds_revisions_leaves_the_row_at_the_last_one(
    db_pool: asyncpg.Pool, lookup: PostgresSetupSummaryLookup
) -> None:
    """The case an increment would get wrong. A replay delivers revision 2
    to a row already at 3, and then 3 again: a statement that added one per
    revision would leave the row at 5, and one that wrote whatever arrived
    last without the forward-only guard would pass through 2 on the way.
    What is asserted is where it ends, and that the time stayed with the
    number."""
    writer = _DrainingSetupWriter(db_pool)
    setup_id = uuid4()
    await writer.define(
        setup_id=setup_id,
        beamline=SetupBeamline("2-bm"),
        operation_id=uuid4(),
        name=SetupName("tomo-default"),
        at=_WHEN,
    )
    await writer.revise(setup_id=setup_id, at=_WHEN + timedelta(minutes=10))
    await writer.revise(setup_id=setup_id, at=_WHEN + timedelta(minutes=20))
    first = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=10, cursor=None
    )

    await _rewind_and_replay(db_pool)

    after = await lookup.list_setups(
        beamline=None, operation_id=None, name=None, limit=10, cursor=None
    )
    assert after == first
    (summary,) = after.items
    assert (summary.revision, summary.revised_at) == (3, _WHEN + timedelta(minutes=20))


async def test_a_revision_redelivered_onto_a_row_already_past_it_moves_nothing(
    db_pool: asyncpg.Pool, lookup: PostgresSetupSummaryLookup
) -> None:
    """The forward-only guard, driven directly rather than through a whole
    replay, so the one statement it lives in is the thing under test."""
    writer = _DrainingSetupWriter(db_pool)
    setup_id = uuid4()
    await writer.define(
        setup_id=setup_id,
        beamline=SetupBeamline("2-bm"),
        operation_id=uuid4(),
        name=SetupName("tomo-default"),
        at=_WHEN,
    )
    await writer.revise(setup_id=setup_id, at=_WHEN + timedelta(minutes=10))
    await writer.revise(setup_id=setup_id, at=_WHEN + timedelta(minutes=20))
    rows, _version = await PostgresEventStore(db_pool).load("Setup", setup_id)
    revision_two = rows[1]
    assert revision_two.payload["revision"] == 2

    async with db_pool.acquire() as conn, conn.transaction():
        await SetupSummaryProjection().apply(revision_two, conn)

    (summary,) = (
        await lookup.list_setups(beamline=None, operation_id=None, name=None, limit=10, cursor=None)
    ).items
    assert (summary.revision, summary.revised_at) == (3, _WHEN + timedelta(minutes=20))
