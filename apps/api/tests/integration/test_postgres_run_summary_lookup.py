"""The projection and its query, against a real Postgres.

The other side of the run-summary contract, and the only place the whole
read path runs: events into the log, the worker's advance loop over them,
rows into `proj_execution_run_summary`, and the query reading them back.

The writer here appends and then drains, so every check in the shared
contract is really asserting "once the projection has caught up". That is
the one thing the in-memory driver cannot say, because a fold has nothing
to catch up to, and it is the reason the lag questions below are here
rather than in the contract.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import asyncpg
import pytest

from aroc.execution.adapters.postgres_run_summary_lookup import PostgresRunSummaryLookup
from aroc.execution.projections.run_summary import RunSummaryProjection
from aroc.infrastructure.adapters.postgres_event_store import PostgresEventStore
from aroc.infrastructure.projection.worker import advance_subscriber_once
from aroc.shared.identifier import Identifier
from tests._port_contracts._writers import EventStoreRunWriter
from tests._port_contracts.run_summary_lookup import CHECKS, Check

pytestmark = [pytest.mark.integration]


class _DrainingRunWriter:
    """Append run events, then let the projection catch up.

    The contract's checks read immediately after writing, which is exactly
    the race a projection has. Draining here rather than inside each check
    keeps the contract about what the adapters answer and leaves when they
    answer it to this tier.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._writer = EventStoreRunWriter(PostgresEventStore(pool))
        self._projection = RunSummaryProjection()

    async def report(
        self,
        *,
        run_id: UUID,
        plan_id: UUID,
        external_ref: Identifier,
        at: datetime,
    ) -> None:
        await self._writer.report(run_id=run_id, plan_id=plan_id, external_ref=external_ref, at=at)
        await self._drain()

    async def complete(self, *, run_id: UUID, at: datetime) -> None:
        await self._writer.complete(run_id=run_id, at=at)
        await self._drain()

    async def _drain(self) -> None:
        while await advance_subscriber_once(self._pool, self._projection):
            pass


@pytest.fixture
def lookup(db_pool: asyncpg.Pool) -> PostgresRunSummaryLookup:
    return PostgresRunSummaryLookup(db_pool)


@pytest.fixture
def writer(db_pool: asyncpg.Pool) -> _DrainingRunWriter:
    return _DrainingRunWriter(db_pool)


@pytest.mark.parametrize("check", CHECKS, ids=lambda c: c.__name__)
async def test_the_postgres_run_summary_lookup_keeps_the_port_contract(
    check: Check, lookup: PostgresRunSummaryLookup, writer: _DrainingRunWriter
) -> None:
    await check(lookup, writer)


async def test_the_migration_seeded_the_bookmark_this_projection_reads(
    db_pool: asyncpg.Pool,
) -> None:
    """Without the row the worker raises on its first advance, forever,
    inside its own backoff loop. Nothing else in the suite would say so:
    the checks above create it implicitly by succeeding."""
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_position FROM projection_bookmarks WHERE name = $1",
            RunSummaryProjection.name,
        )
    assert row is not None
    assert row["last_position"] == 0


async def test_a_run_is_invisible_until_the_projection_has_caught_up(
    db_pool: asyncpg.Pool, lookup: PostgresRunSummaryLookup
) -> None:
    """The one behaviour that only exists on this side of the port, and
    the one thing a caller has to know: a write returns before the read
    model shows it. Asserting it here is what stops somebody 'fixing' the
    lag by reading in the request path."""
    writer = EventStoreRunWriter(PostgresEventStore(db_pool))
    await writer.report(
        run_id=uuid4(),
        plan_id=uuid4(),
        external_ref=Identifier(scheme="bluesky-run-uid", value="a"),
        at=datetime.now(tz=UTC),
    )

    before = await lookup.list_runs(external_ref=None, limit=10, cursor=None)
    assert before.items == []

    await advance_subscriber_once(db_pool, RunSummaryProjection())

    after = await lookup.list_runs(external_ref=None, limit=10, cursor=None)
    assert len(after.items) == 1


async def test_replaying_a_batch_leaves_the_table_exactly_as_it_was(
    db_pool: asyncpg.Pool, lookup: PostgresRunSummaryLookup
) -> None:
    """Delivery is at-least-once, so a crash between applying a batch and
    committing the bookmark replays it. Rewinding the bookmark by hand is
    the only way to make that happen on demand."""
    writer = _DrainingRunWriter(db_pool)
    run_id = uuid4()
    started = datetime.now(tz=UTC)
    await writer.report(
        run_id=run_id,
        plan_id=uuid4(),
        external_ref=Identifier(scheme="bluesky-run-uid", value="a"),
        at=started,
    )
    await writer.complete(run_id=run_id, at=started + timedelta(minutes=3))
    first = await lookup.list_runs(external_ref=None, limit=10, cursor=None)

    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE projection_bookmarks SET last_transaction_id = '0'::xid8, "
            "last_position = 0 WHERE name = $1",
            RunSummaryProjection.name,
        )
    while await advance_subscriber_once(db_pool, RunSummaryProjection()):
        pass

    assert await lookup.list_runs(external_ref=None, limit=10, cursor=None) == first


async def test_an_ending_for_a_run_the_table_never_saw_does_not_wedge_the_worker(
    db_pool: asyncpg.Pool, lookup: PostgresRunSummaryLookup
) -> None:
    """A transition with no row ahead of it cannot happen through the
    ordering, and if it ever did, stopping the whole read model over one
    run would be the wrong answer. Narrowing the subscription to endings
    only is how a projection that missed a genesis is simulated."""
    run_id = uuid4()
    writer = EventStoreRunWriter(PostgresEventStore(db_pool))
    await writer.report(
        run_id=run_id,
        plan_id=uuid4(),
        external_ref=Identifier(scheme="bluesky-run-uid", value="a"),
        at=datetime.now(tz=UTC),
    )
    await writer.complete(run_id=run_id, at=datetime.now(tz=UTC))

    endings_only = RunSummaryProjection()
    endings_only.subscribed_event_types = frozenset({"RunCompleted"})

    assert await advance_subscriber_once(db_pool, endings_only) == 1

    page = await lookup.list_runs(external_ref=None, limit=10, cursor=None)
    assert page.items == []
