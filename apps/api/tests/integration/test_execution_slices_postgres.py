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

import asyncio
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from aroc.execution import wire_execution
from aroc.execution.aggregates.plan import PlanName, PlanNotFoundError, load_plan
from aroc.execution.aggregates.run import (
    RunCannotBeAbortedError,
    RunCannotBeCompletedError,
    RunCannotBePausedError,
    RunNotFoundError,
    RunStatus,
    load_run,
)
from aroc.execution.features.abort_run import AbortRun
from aroc.execution.features.complete_run import CompleteRun
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.get_plan import GetPlan
from aroc.execution.features.get_run import GetRun
from aroc.execution.features.pause_run import PauseRun
from aroc.execution.features.report_run import ReportRun
from aroc.execution.features.resume_run import ResumeRun
from aroc.execution.wire import ExecutionHandlers
from aroc.infrastructure.adapters.postgres_event_store import PostgresEventStore
from aroc.infrastructure.deps import make_postgres_kernel
from aroc.infrastructure.ports import ConcurrencyError
from aroc.infrastructure.ports.authorize import AllowAllAuthorize
from aroc.infrastructure.ports.clock import SystemClock
from aroc.infrastructure.ports.id_generator import UUIDv7Generator
from aroc.infrastructure.settings import Settings
from aroc.shared.identifier import Identifier

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

_REF = Identifier(scheme="bluesky-run-uid", value="f1e2d3c4")


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


async def _a_reported_run(handlers: ExecutionHandlers) -> UUID:
    """A plan and a run of it, through the wired handlers. Returns the run id."""
    plan_id = await handlers.define_plan(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await handlers.report_run(
        ReportRun(
            plan_id=plan_id,
            parameters={"exposure_seconds": 0.25, "detector": "eiger"},
            external_ref=_REF,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
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


async def test_a_run_survives_a_round_trip_and_names_the_plan_it_ran(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """Two streams, two stream types, one pool.

    The cross-aggregate read is the part real SQL adds here. The unit
    tests run it against a store that hands back the objects it was
    given, so a plan that never went through a serialiser proved the
    schema was readable. Here the decider checks the run's parameters
    against a schema that came back out of JSONB.
    """
    plan_id = await handlers.define_plan(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    run_id = await handlers.report_run(
        ReportRun(
            plan_id=plan_id,
            parameters={"exposure_seconds": 0.25, "detector": "eiger"},
            external_ref=_REF,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    store = PostgresEventStore(db_pool)
    run = await load_run(store, run_id)
    assert run is not None
    assert run.plan_id == plan_id
    assert run.parameters == {"exposure_seconds": 0.25, "detector": "eiger"}
    assert run.external_ref == _REF


async def test_a_run_and_its_plan_are_filed_under_different_stream_types(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """Read the raw rows, so the routing key is asserted and not assumed.

    Both aggregates live in one context and one table, and the only
    thing keeping their histories apart is the `stream_type` column.
    Two aggregates writing under one value would fold each other's rows,
    and every fold-based test would still pass on a store that hands
    back only what it was asked for.
    """
    plan_id = await handlers.define_plan(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    run_id = await handlers.report_run(
        ReportRun(
            plan_id=plan_id,
            parameters={"exposure_seconds": 0.25, "detector": "eiger"},
            external_ref=_REF,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows = await db_pool.fetch(
        "SELECT stream_type, stream_id, event_type FROM events "
        "WHERE stream_id = ANY($1::uuid[]) ORDER BY position",
        [plan_id, run_id],
    )

    assert [(r["stream_type"], r["event_type"]) for r in rows] == [
        ("Plan", "PlanDefined"),
        ("Run", "RunReported"),
    ]


async def test_recording_against_a_plan_that_does_not_exist_is_refused(
    handlers: ExecutionHandlers,
) -> None:
    with pytest.raises(PlanNotFoundError):
        await handlers.report_run(
            ReportRun(plan_id=uuid4(), parameters={"exposure_seconds": 0.25}, external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_reading_a_run_that_was_never_recorded_is_refused(
    handlers: ExecutionHandlers,
) -> None:
    with pytest.raises(RunNotFoundError):
        await handlers.get_run(GetRun(run_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4())


async def test_two_concurrent_endings_leave_one_winner(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The UNIQUE constraint decides, not a Python lock.

    Both callers fold the same running run and both try to append at the
    same version. In memory a lock serialises them and the loser meets
    the decider's refusal instead; here the second INSERT violates
    events_stream_version_unique and the adapter turns that into
    ConcurrencyError. Either way exactly one ending lands, which is the
    invariant, and only real SQL exercises the mechanism that enforces it
    in production.

    Two DIFFERENT endings on purpose. Two completions would also be
    refused by the idempotent-looking path, and what needs pinning is
    that a run cannot end twice even when the two callers disagree about
    how it ended.
    """
    run_id = await _a_reported_run(handlers)

    results = await asyncio.gather(
        handlers.complete_run(
            CompleteRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
        ),
        handlers.abort_run(AbortRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 1, f"expected exactly one loser, got {results}"
    assert isinstance(
        failures[0],
        ConcurrencyError | RunCannotBeCompletedError | RunCannotBeAbortedError,
    )

    endings = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_id = $1 AND event_type <> 'RunReported'",
        run_id,
    )
    assert endings == 1


async def test_an_ending_survives_the_round_trip_and_shows_on_the_read_slice(
    handlers: ExecutionHandlers,
) -> None:
    """The status is derived, so it has to survive a reload to mean anything.

    The unit tests fold events they built in memory. Here the ending goes
    to Postgres, comes back through the codec, and the fold recomputes
    the status from the event type on the row. A status that was written
    onto a payload would pass both; one that is derived only passes if
    the row's type came back intact.
    """
    run_id = await _a_reported_run(handlers)

    await handlers.abort_run(AbortRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())
    run = await handlers.get_run(
        GetRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert run.status is RunStatus.ABORTED


async def test_a_pause_cycle_survives_the_round_trip_and_reads_back_as_running(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """A status the stream returns to, recovered from rows rather than memory.

    The ending round trip above starts and finishes on different
    statuses, so a fold that stopped reading after the second row would
    still get it right. This one starts and finishes on the same one,
    which is what makes the row count the load-bearing assertion: the
    status alone cannot tell a completed cycle from two appends that
    never happened.
    """
    run_id = await _a_reported_run(handlers)

    await handlers.pause_run(PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())
    paused = await handlers.get_run(
        GetRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    await handlers.resume_run(
        ResumeRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    resumed = await handlers.get_run(
        GetRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert (paused.status, resumed.status) == (RunStatus.PAUSED, RunStatus.RUNNING)

    written = await db_pool.fetch(
        "SELECT event_type FROM events WHERE stream_id = $1 ORDER BY version",
        run_id,
    )
    assert [row["event_type"] for row in written] == [
        "RunReported",
        "RunPaused",
        "RunResumed",
    ]


async def test_two_concurrent_pauses_leave_one_winner(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The same race as the endings, on the one move that can be undone.

    Worth running separately rather than trusting the endings case. A
    pause is the transition an adapter is most likely to redeliver, since
    an engine can pause and resume many times in a run and a reporter
    that loses its place replays from the last thing it is sure of. Both
    callers fold a running run and both append at version one; the
    UNIQUE constraint is what makes the second a loser rather than a
    second pause on a paused run.
    """
    run_id = await _a_reported_run(handlers)

    results = await asyncio.gather(
        handlers.pause_run(PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()),
        handlers.pause_run(PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()),
        return_exceptions=True,
    )

    failures = [r for r in results if isinstance(r, BaseException)]
    assert len(failures) == 1, f"expected exactly one loser, got {results}"
    assert isinstance(failures[0], ConcurrencyError | RunCannotBePausedError)

    pauses = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_id = $1 AND event_type = 'RunPaused'",
        run_id,
    )
    assert pauses == 1


async def test_a_reported_time_is_stored_as_given_and_the_write_time_is_not(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The two timestamps, read off a real row, side by side.

    This is the only tier that can see the change at all. The read model
    exposes no times, so the unit and contract tiers can prove the field
    reaches the command and not that it reaches the column.

    Both halves matter. `occurred_at` must be exactly the instant the
    caller reported, years before this test runs, which says a backfill
    lands honestly. `recorded_at` must be near now and nowhere near the
    reported time, which says a caller cannot touch it: it comes from the
    table's own DEFAULT, never from this application. That split is the
    whole reason an unchecked instant is safe to accept.
    """
    reported = datetime(2019, 3, 4, 9, 30, tzinfo=UTC)
    plan_id = await handlers.define_plan(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    run_id = await handlers.report_run(
        ReportRun(
            plan_id=plan_id,
            parameters={"exposure_seconds": 0.25, "detector": "eiger"},
            external_ref=_REF,
            occurred_at=reported,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    row = await db_pool.fetchrow(
        "SELECT occurred_at, recorded_at FROM events WHERE stream_id = $1",
        run_id,
    )

    assert row["occurred_at"] == reported
    assert row["recorded_at"] != reported
    assert (row["recorded_at"] - reported).days > 365, (
        "recorded_at must be the store's own write time, not the reported one"
    )


async def test_a_transition_with_no_reported_time_is_stamped_by_the_clock(
    handlers: ExecutionHandlers, db_pool: asyncpg.Pool
) -> None:
    """The fallback, against real SQL, so the column is never left null.

    `occurred_at` is NOT NULL with no database default, so a handler that
    passed the command's `None` straight through would raise on insert
    rather than quietly storing nothing. Worth pinning here because the
    in-memory store would accept a null without complaint.
    """
    run_id = await _a_reported_run(handlers)

    await handlers.complete_run(
        CompleteRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    stamps = await db_pool.fetch(
        "SELECT occurred_at FROM events WHERE stream_id = $1 ORDER BY version",
        run_id,
    )
    assert all(row["occurred_at"] is not None for row in stamps)
    assert len(stamps) == 2


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
