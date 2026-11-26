"""Defining a setup, driven end to end against a real Postgres.

The unit tests run on `InMemoryEventStore`, which hands back the very
objects it was given, and on the in-memory lookup, which folds the streams
and so sees a definition the instant it lands. Neither is what a
deployment runs, and each hides one thing this file is for.

The documents are the first. In a row the settings and their schema are
JSONB that went out through a serialiser and came back through a codec,
and the schema is what a conductor and a caller check values against.

The key check is the second. In a deployment it reads a table a projection
worker fills, so it can only refuse a definition the worker has already
seen. Both sides of that are driven here: refused once the projection has
caught up, and let through while it has not, which is the window the
handler's docstring calls a check rather than a lock.

The queries spell `"Setup"` as a literal rather than using
`SETUP_STREAM_TYPE`, which is the only independent side these tests have.
The handlers come from `wire_execution`, not from `bind`, so these go
through the same composition the application boots: tracing, the
idempotency wrapper, and the lookup the wiring picks for a pool.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import json
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution import wire_execution
from keeper.execution.aggregates.setup import SetupAlreadyExistsError, load_setup
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_setup import DefineSetup
from keeper.execution.features.get_setup import GetSetup
from keeper.execution.features.list_setups import ListSetups
from keeper.execution.features.revise_setup import ReviseSetup
from keeper.execution.projections.setup_summary import SetupSummaryProjection
from keeper.execution.wire import ExecutionHandlers
from keeper.infrastructure.adapters.postgres_event_store import PostgresEventStore
from keeper.infrastructure.deps import make_postgres_kernel
from keeper.infrastructure.ports.authorize import AllowAllAuthorize
from keeper.infrastructure.ports.clock import SystemClock
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.projection.worker import advance_subscriber_once
from keeper.infrastructure.settings import Settings

pytestmark = [pytest.mark.integration]

_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "config": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
        "override": {"type": "object"},
    },
}

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "rotation-axis": {"type": "number", "unit": {"system": "udunits", "code": "pixel"}},
        "binning": {"type": "integer", "enum": [1, 2, 4]},
        "filter": {"type": "string", "pattern": "^[A-Z][a-z]?$"},
    },
    "required": ["rotation-axis"],
}
"""Nested and multi-keyword on purpose.

An object inside an object, a list inside that, a unit annotation and a
pattern: where a codec that flattened, reordered or stringified something
would show up.
"""

_SETTINGS: dict[str, Any] = {"rotation-axis": 1630.25, "binning": 2, "filter": "Al"}


@pytest.fixture
def handlers(db_pool: asyncpg.Pool) -> ExecutionHandlers:
    """The Execution bundle, wired exactly as the application wires it."""
    return wire_execution(
        make_postgres_kernel(
            db_pool,
            settings=Settings(environment="test"),
            clock=SystemClock(),
            id_generator=UUIDv7Generator(),
            authz=AllowAllAuthorize(),
        )
    )


async def _an_operation(handlers: ExecutionHandlers) -> UUID:
    return await handlers.define_operation(
        DefineOperation(name="process", parameters_schema=_PROCESS_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


def _command(operation_id: UUID) -> DefineSetup:
    return DefineSetup(
        beamline="2-bm",
        operation_id=operation_id,
        name="tomo-default",
        settings=_SETTINGS,
        settings_schema=_SETTINGS_SCHEMA,
    )


async def _drain(pool: asyncpg.Pool) -> None:
    """Let the setup projection catch up, as the worker would."""
    while await advance_subscriber_once(pool, SetupSummaryProjection()):
        pass


async def test_a_setup_survives_a_round_trip_through_jsonb(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """Fold what Postgres gives back, not what was handed to the store."""
    operation_id = await _an_operation(handlers)

    setup_id = await handlers.define_setup(
        _command(operation_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    setup = await load_setup(PostgresEventStore(db_pool), setup_id)
    assert setup is not None
    assert (setup.operation_id, setup.revision) == (operation_id, 1)
    assert setup.settings == _SETTINGS
    assert setup.settings_schema == _SETTINGS_SCHEMA


async def test_the_stored_row_holds_both_documents_under_the_pinned_stream_type(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """Read the raw JSONB, so the shape is asserted and not just the fold.

    `payload::text` rather than `payload`, because the pool registers a
    JSONB codec and the plain column comes back already decoded.
    """
    setup_id = await handlers.define_setup(
        _command(await _an_operation(handlers)), principal_id=uuid4(), correlation_id=uuid4()
    )

    row = await db_pool.fetchrow(
        "SELECT event_type, payload::text AS payload FROM events "
        "WHERE stream_type = $1 AND stream_id = $2",
        "Setup",
        setup_id,
    )

    assert row is not None
    assert row["event_type"] == "SetupDefined"
    payload = json.loads(row["payload"])
    assert payload["setup_name"] == "tomo-default"
    assert payload["settings"] == _SETTINGS
    assert payload["settings_schema"] == _SETTINGS_SCHEMA
    assert "name" not in payload, "the bare key is what the personal-data rule refuses"


async def test_every_revision_reads_back_from_a_real_stream(
    handlers: ExecutionHandlers,
) -> None:
    """The read slice folds as far as the revision asked for, and every
    revision it folds through came back out of JSONB."""
    setup_id = await handlers.define_setup(
        _command(await _an_operation(handlers)), principal_id=uuid4(), correlation_id=uuid4()
    )
    revised = await handlers.revise_setup(
        ReviseSetup(
            setup_id=setup_id,
            expected_revision=1,
            settings={**_SETTINGS, "binning": 4},
            settings_schema=_SETTINGS_SCHEMA,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    first = await handlers.get_setup(
        GetSetup(setup_id=setup_id, revision=1), principal_id=uuid4(), correlation_id=uuid4()
    )
    latest = await handlers.get_setup(
        GetSetup(setup_id=setup_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert revised == 2
    assert (first.revision, first.settings["binning"]) == (1, 2)
    assert (latest.revision, latest.settings["binning"]) == (2, 4)


async def test_a_second_definition_is_refused_once_the_projection_has_caught_up(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    operation_id = await _an_operation(handlers)
    first = await handlers.define_setup(
        _command(operation_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    await _drain(db_pool)

    with pytest.raises(SetupAlreadyExistsError, match=str(first)):
        await handlers.define_setup(
            _command(operation_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    written = await db_pool.fetchval("SELECT count(*) FROM events WHERE stream_type = 'Setup'")
    assert written == 1


async def test_a_second_definition_before_the_projection_catches_up_gets_through(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The window, shown rather than described. The key check reads the
    table, and the table has not seen the first definition yet, so the
    second lands too. What is left behind is two setups under one key, both
    in the listing, and the first defined is the one a key lookup answers
    with."""
    operation_id = await _an_operation(handlers)
    first = await handlers.define_setup(
        _command(operation_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    second = await handlers.define_setup(
        _command(operation_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    await _drain(db_pool)

    listed = await handlers.list_setups(
        ListSetups.from_filters(beamline="2-bm", operation_id=operation_id, name="tomo-default"),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert first != second
    assert {summary.setup_id for summary in listed.items} == {first, second}
    with pytest.raises(SetupAlreadyExistsError, match=str(first)):
        await handlers.define_setup(
            _command(operation_id), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_replaying_an_idempotency_key_writes_one_stream(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The wrapper is in the bundle, so the retry is checked through it, and
    against the table rather than against the two ids. A wrapper that
    returned the cached id while still appending would pass the contract
    test and leave a second setup behind; here the key check would not
    catch it either, because the projection has not run."""
    command = _command(await _an_operation(handlers))
    caller = uuid4()

    first = await handlers.define_setup(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key="a-retried-request"
    )
    second = await handlers.define_setup(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key="a-retried-request"
    )

    assert first == second
    written = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_type = $1 AND stream_id = $2", "Setup", first
    )
    assert written == 1
    assert await db_pool.fetchval("SELECT count(*) FROM events WHERE stream_type = 'Setup'") == 1
