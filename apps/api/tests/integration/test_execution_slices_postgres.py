"""The Execution slices, driven end to end against a real Postgres.

Every other test of this context runs on `InMemoryEventStore`, which
hands back the very objects it was given. The parameters schema is the
reason that is not good enough here. In state it is a Python dict; in a
row it is a JSONB document that went out through a serialiser and came
back through a codec. A plan that folds correctly from a dict it never
serialised proves nothing about the one the deployed system reads back,
and the schema is the field a caller validates its own requests against.

The queries below spell `"Plan"` as a literal rather than using
`PLAN_STREAM_TYPE`. That is the only independent side these tests have:
a query built from the writer's own constant agrees with the writer
however wrong the constant is.

The handlers come from `wire_execution`, not from `bind`, so these go
through the same composition the application boots: tracing and the
idempotency wrapper.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import json
from typing import Any
from uuid import uuid4

import asyncpg
import pytest

from aroc.execution import wire_execution
from aroc.execution.aggregates.plan import PlanName, PlanNotFoundError, load_plan
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.get_plan import GetPlan
from aroc.execution.wire import ExecutionHandlers
from aroc.infrastructure.adapters.postgres_event_store import PostgresEventStore
from aroc.infrastructure.deps import make_postgres_kernel
from aroc.infrastructure.ports.authorize import AllowAllAuthorize
from aroc.infrastructure.ports.clock import SystemClock
from aroc.infrastructure.ports.id_generator import UUIDv7Generator
from aroc.infrastructure.settings import Settings

pytestmark = [pytest.mark.integration]

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "exposure_seconds": {"type": "number", "minimum": 0},
        "detector": {"type": "string", "enum": ["pilatus", "eiger"]},
    },
    "required": ["exposure_seconds", "detector"],
}
"""Nested and multi-keyword on purpose.

A flat one-property schema would survive almost any serialisation
mistake. This one has an object inside an object and a list inside that,
which is where a codec that flattened, reordered or stringified
something would show up.
"""


@pytest.fixture
def handlers(db_pool: asyncpg.Pool) -> ExecutionHandlers:
    """The Execution bundle, wired exactly as the application wires it."""
    return wire_execution(
        make_postgres_kernel(
            db_pool,
            settings=Settings(app_env="test"),
            clock=SystemClock(),
            id_generator=UUIDv7Generator(),
            authz=AllowAllAuthorize(),
        )
    )


async def test_a_plan_survives_a_round_trip_through_jsonb(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """Fold what Postgres gives back, not what was handed to the store."""
    plan_id = await handlers.define_plan(
        DefinePlan(name="grid_scan", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    store = PostgresEventStore(db_pool)
    plan = await load_plan(store, plan_id)

    assert plan is not None
    assert plan.id == plan_id
    assert plan.name == PlanName("grid_scan")
    assert plan.parameters_schema == _SCHEMA


async def test_the_stored_row_holds_the_schema_under_the_pinned_stream_type(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """Read the raw JSONB, so the shape is asserted and not just the fold.

    A fold that agrees with itself would pass even if the schema were
    stored as a string, or with its keys renamed. The stored shape is a
    contract with every future reader of this table, so it is checked
    directly rather than through the reader that wrote it.
    """
    plan_id = await handlers.define_plan(
        DefinePlan(name="grid_scan", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    # `payload::text` rather than `payload`: the pool registers a JSONB
    # codec, so the plain column comes back already decoded. Reading the
    # text is reading what the column holds.
    row = await db_pool.fetchrow(
        "SELECT event_type, payload::text AS payload FROM events "
        "WHERE stream_type = $1 AND stream_id = $2",
        "Plan",
        plan_id,
    )

    assert row is not None
    assert row["event_type"] == "PlanDefined"
    payload = json.loads(row["payload"])
    assert payload["plan_name"] == "grid_scan"
    assert payload["parameters_schema"] == _SCHEMA
    assert "name" not in payload, "the bare key is what the personal-data rule refuses"


async def test_the_read_slice_answers_from_a_real_stream(
    handlers: ExecutionHandlers,
) -> None:
    """Both slices through one pool, which is how the application runs them."""
    plan_id = await handlers.define_plan(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    plan = await handlers.get_plan(
        GetPlan(plan_id=plan_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert plan.id == plan_id
    assert plan.name == PlanName("count")


async def test_reading_a_plan_that_was_never_defined_is_refused(
    handlers: ExecutionHandlers,
) -> None:
    with pytest.raises(PlanNotFoundError):
        await handlers.get_plan(
            GetPlan(plan_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )


async def test_replaying_an_idempotency_key_writes_one_stream(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The wrapper is in the bundle, so the retry has to be checked through it.

    The unit tests call the bare handler, which has no wrapper at all,
    and the contract test checks the two ids match. Neither looks at the
    table. A wrapper that returned the cached id while still appending
    would pass both and leave a second plan behind.
    """
    command = DefinePlan(name="count", parameters_schema=_SCHEMA)
    caller = uuid4()

    first = await handlers.define_plan(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key="a-retried-request"
    )
    second = await handlers.define_plan(
        command, principal_id=caller, correlation_id=uuid4(), idempotency_key="a-retried-request"
    )

    assert first == second
    written = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_type = $1 AND stream_id = $2", "Plan", first
    )
    assert written == 1
