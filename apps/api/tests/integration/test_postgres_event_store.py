"""The event store, against a real Postgres.

This adapter is the one piece of infrastructure whose bugs are unrecoverable.
Every other component can be rebuilt from the event log; the event log cannot
be rebuilt from anything. Its three guarantees are all properties of the
database rather than of the Python, so none of them can be checked against a
fake:

  - a stale writer is refused rather than silently interleaved
  - an append is all-or-nothing, across several streams at once
  - the `transaction_id` watermark is assigned by Postgres at commit, which is
    what lets a projection resume without skipping a slow transaction

The optimistic-concurrency case has a subtlety worth naming. Two different
UNIQUE constraints can fire on the same INSERT, and only one of them means
"someone else got there first". Mapping both to `ConcurrencyError` would turn
a duplicate-event-id bug into an infinite retry loop.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg
import pytest

from aroc.infrastructure.adapters.postgres_event_store import PostgresEventStore
from aroc.infrastructure.ports.event_store import ConcurrencyError, NewEvent, StreamAppend

pytestmark = [pytest.mark.integration]


def _event(
    event_type: str = "ThingRegistered",
    *,
    event_id: UUID | None = None,
) -> NewEvent:
    return NewEvent(
        event_id=event_id or uuid4(),
        event_type=event_type,
        schema_version=1,
        payload={"note": event_type},
        occurred_at=datetime.now(UTC),
        correlation_id=uuid4(),
        metadata={"command": "DoThing"},
        principal_id=uuid4(),
    )


@pytest.fixture
def store(db_pool: asyncpg.Pool) -> PostgresEventStore:
    return PostgresEventStore(db_pool)


async def test_appended_events_load_back_in_version_order(store: PostgresEventStore) -> None:
    stream = uuid4()
    await store.append("thing", stream, 0, [_event("ThingRegistered"), _event("ThingRenamed")])

    loaded, version = await store.load("thing", stream)
    assert [e.event_type for e in loaded] == ["ThingRegistered", "ThingRenamed"]
    assert [e.version for e in loaded] == [1, 2]
    assert version == 2


async def test_append_numbers_the_first_event_one_and_returns_the_new_version(
    store: PostgresEventStore,
) -> None:
    stream = uuid4()
    assert await store.append("thing", stream, 0, [_event()]) == 1
    assert await store.append("thing", stream, 1, [_event(), _event()]) == 3


async def test_loading_a_stream_that_was_never_written_returns_nothing(
    store: PostgresEventStore,
) -> None:
    assert await store.load("thing", uuid4()) == ([], 0)


async def test_load_returns_only_the_stream_asked_for(store: PostgresEventStore) -> None:
    mine, theirs = uuid4(), uuid4()
    await store.append("thing", mine, 0, [_event("Mine")])
    await store.append("thing", theirs, 0, [_event("Theirs")])
    events, _ = await store.load("thing", mine)
    assert [e.event_type for e in events] == ["Mine"]


async def test_two_streams_may_share_an_id_under_different_stream_types(
    store: PostgresEventStore,
) -> None:
    """The uniqueness key is (stream_type, stream_id, version), so the same
    UUID under two types is two streams, each numbered from one."""
    shared = uuid4()
    await store.append("thing", shared, 0, [_event("A")])
    await store.append("other", shared, 0, [_event("B")])
    thing_events, _ = await store.load("thing", shared)
    other_events, _ = await store.load("other", shared)
    assert [e.event_type for e in thing_events] == ["A"]
    assert [e.event_type for e in other_events] == ["B"]


async def test_a_stale_writer_is_refused_and_told_the_actual_version(
    store: PostgresEventStore,
) -> None:
    stream = uuid4()
    await store.append("thing", stream, 0, [_event(), _event()])

    with pytest.raises(ConcurrencyError) as caught:
        await store.append("thing", stream, 0, [_event()])
    assert caught.value.expected == 0
    assert caught.value.actual == 2


async def test_a_refused_append_writes_none_of_its_events(store: PostgresEventStore) -> None:
    stream = uuid4()
    await store.append("thing", stream, 0, [_event("First")])
    with pytest.raises(ConcurrencyError):
        await store.append("thing", stream, 0, [_event("Doomed"), _event("AlsoDoomed")])
    events, _ = await store.load("thing", stream)
    assert [e.event_type for e in events] == ["First"]


async def test_a_duplicate_event_id_is_raised_as_itself_not_as_a_concurrency_error(
    store: PostgresEventStore,
) -> None:
    """Two UNIQUE constraints can fire on one INSERT and they mean different
    things. A reused event id is a generator bug: mapping it to
    ConcurrencyError would send the caller into a retry loop that reloads,
    re-appends the same id, and fails identically forever.
    """
    reused = uuid4()
    await store.append("thing", uuid4(), 0, [_event(event_id=reused)])

    with pytest.raises(asyncpg.UniqueViolationError) as caught:
        await store.append("thing", uuid4(), 0, [_event(event_id=reused)])
    assert not isinstance(caught.value, ConcurrencyError)


async def test_appending_no_events_is_a_no_op_that_reports_the_version_back(
    store: PostgresEventStore,
) -> None:
    stream = uuid4()
    await store.append("thing", stream, 0, [_event()])
    assert await store.append("thing", stream, 1, []) == 1
    events, _ = await store.load("thing", stream)
    assert len(events) == 1


async def test_a_multi_stream_append_commits_every_stream_or_none_of_them(
    store: PostgresEventStore,
) -> None:
    """The reason append_streams exists. A saga writing two aggregates must
    not leave one written and the other not, because there is no compensating
    write that can un-append an event."""
    good, stale = uuid4(), uuid4()
    await store.append("thing", stale, 0, [_event("Existing")])

    with pytest.raises(ConcurrencyError):
        await store.append_streams(
            [
                StreamAppend("thing", good, 0, [_event("ShouldNotLand")]),
                StreamAppend("thing", stale, 0, [_event("Conflicts")]),
            ]
        )
    assert await store.load("thing", good) == ([], 0), "the other stream rolled back too"


async def test_a_multi_stream_append_that_succeeds_reports_each_new_version(
    store: PostgresEventStore,
) -> None:
    one, two = uuid4(), uuid4()
    versions = await store.append_streams(
        [
            StreamAppend("thing", one, 0, [_event()]),
            StreamAppend("thing", two, 0, [_event(), _event()]),
        ]
    )
    assert versions == {one: 1, two: 2}


async def test_a_stream_with_no_events_still_reports_its_version_in_the_result(
    store: PostgresEventStore,
) -> None:
    written, empty = uuid4(), uuid4()
    versions = await store.append_streams(
        [
            StreamAppend("thing", written, 0, [_event()]),
            StreamAppend("thing", empty, 7, []),
        ]
    )
    assert versions == {written: 1, empty: 7}


async def test_an_append_on_the_callers_connection_rolls_back_with_their_transaction(
    store: PostgresEventStore, db_pool: asyncpg.Pool
) -> None:
    """The `conn=` path exists so an erasure slice can delete personal data and
    append its audit event atomically. If the append did not join the caller's
    transaction, the two halves could diverge."""
    stream = uuid4()
    async with db_pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        await store.append_streams([StreamAppend("thing", stream, 0, [_event()])], conn=conn)
        await transaction.rollback()

    assert await store.load("thing", stream) == ([], 0)


async def test_every_stored_event_carries_the_commit_watermark_a_projection_reads(
    store: PostgresEventStore,
) -> None:
    """`transaction_id` is assigned by Postgres, not by this process. It is
    what makes the projection cursor safe against a slow transaction that
    commits after a faster one with a higher position."""
    stream = uuid4()
    await store.append("thing", stream, 0, [_event(), _event()])

    loaded, _ = await store.load("thing", stream)
    assert all(isinstance(e.transaction_id, int) for e in loaded)
    assert all(e.transaction_id > 0 for e in loaded)
    assert loaded[0].position < loaded[1].position


async def test_an_append_notifies_listeners_so_a_projection_wakes_promptly(
    store: PostgresEventStore, db_pool: asyncpg.Pool
) -> None:
    """The wake-up is a latency optimisation, not the source of truth, but a
    trigger that silently stopped firing would leave every projection running
    at the poll interval with nothing to say so."""
    received: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(_conn: object, _pid: int, _channel: str, payload: str) -> None:
        received.put_nowait(payload)

    async with db_pool.acquire() as listener:
        await listener.add_listener("events", _on_notify)
        try:
            await store.append("thing", uuid4(), 0, [_event()])
            await asyncio.wait_for(received.get(), timeout=5.0)
        finally:
            # Same callable object, or asyncpg leaves the listener attached
            # and warns when the connection returns to the pool.
            await listener.remove_listener("events", _on_notify)
