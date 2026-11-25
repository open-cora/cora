"""The boot guard's query finds exactly the work a conductor would take.

`infra/deploy/queued-executions.sql` is what decides whether the keeper's
API comes back on its own after its host reboots. It reads the event log
for executions that were dispatched and neither claimed nor ended, and any
row it returns holds the API until a person releases it.

So the query has two ways to be wrong and they cost different things. A row
too many holds a keeper that could have come back, which somebody notices.
A row too few lets the API start and hands that work to a conductor at
once, which nobody notices until a station moves. These drive real
dispatches, claims and endings through the wired handlers and run the file
itself, as the role the guard connects as.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from keeper.execution import wire_execution
from keeper.execution.aggregates.procedure import RunStep, SetStep
from keeper.execution.features.claim_execution import ClaimExecution
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.execution.features.end_execution import EndExecution
from keeper.execution.wire import ExecutionHandlers
from keeper.infrastructure.deps import make_postgres_kernel
from keeper.infrastructure.ports.authorize import AllowAllAuthorize
from keeper.infrastructure.ports.clock import SystemClock
from keeper.infrastructure.ports.id_generator import UUIDv7Generator
from keeper.infrastructure.settings import Settings
from tests.integration.conftest import ClonedDatabase

pytestmark = [pytest.mark.integration]

_QUERY = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "queued-executions.sql"

_APP_ROLE = "keeper_app"
"""The role the guard connects as, whose password a fresh database leaves equal to its name."""

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


@pytest.fixture
def handlers(db_pool: asyncpg.Pool) -> ExecutionHandlers:
    return wire_execution(
        make_postgres_kernel(
            db_pool,
            settings=Settings(environment="test"),
            clock=SystemClock(),
            id_generator=UUIDv7Generator(),
            authz=AllowAllAuthorize(),
        )
    )


async def _dispatched(handlers: ExecutionHandlers, *, beamline: str, name: str) -> UUID:
    operation_id = await handlers.define_operation(
        DefineOperation(name=f"{name}_count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    procedure_id = await handlers.define_procedure(
        DefineProcedure(
            name=name,
            beamline=beamline,
            steps=(
                SetStep(record="2bmb:m1", to=0.0),
                RunStep(
                    operation_id=operation_id,
                    parameters={"exposure_seconds": 0.25},
                    scopes=("2bmb:det:",),
                ),
            ),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await handlers.dispatch_execution(
        DispatchExecution(procedure_id=procedure_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _queued(cloned_database: ClonedDatabase) -> list[asyncpg.Record]:
    """Run the guard's file as the guard's role, on its own connection."""
    connection = await asyncpg.connect(cloned_database.url_as(_APP_ROLE, _APP_ROLE))
    try:
        return await connection.fetch(_QUERY.read_text(encoding="utf-8"))
    finally:
        await connection.close()


async def test_an_empty_log_holds_nothing(cloned_database: ClonedDatabase) -> None:
    assert await _queued(cloned_database) == []


async def test_a_dispatch_nobody_took_up_is_queued_with_its_beamline_and_procedure(
    handlers: ExecutionHandlers, cloned_database: ClonedDatabase
) -> None:
    waiting = await _dispatched(handlers, beamline="7-bm", name="align_then_scan")

    rows = await _queued(cloned_database)

    assert [(row["execution_id"], row["beamline"], row["procedure_name"]) for row in rows] == [
        (waiting, "7-bm", "align_then_scan")
    ]
    assert str(rows[0]["dispatched_at"]).endswith("Z")


async def test_a_claimed_execution_is_not_queued(
    handlers: ExecutionHandlers, cloned_database: ClonedDatabase
) -> None:
    taken = await _dispatched(handlers, beamline="2-bm", name="taken")
    await handlers.claim_execution(
        ClaimExecution(execution_id=taken), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await _queued(cloned_database) == []


async def test_an_execution_ended_before_anyone_claimed_it_is_not_queued(
    handlers: ExecutionHandlers, cloned_database: ClonedDatabase
) -> None:
    """The release procedure ends stale work this way, so it has to clear the hold."""
    withdrawn = await _dispatched(handlers, beamline="19-bm", name="withdrawn")
    await handlers.end_execution(
        EndExecution(execution_id=withdrawn), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await _queued(cloned_database) == []


async def test_only_the_untaken_ones_are_queued_among_several_oldest_first(
    handlers: ExecutionHandlers, cloned_database: ClonedDatabase
) -> None:
    first = await _dispatched(handlers, beamline="32-id", name="first")
    taken = await _dispatched(handlers, beamline="2-bm", name="taken")
    second = await _dispatched(handlers, beamline="7-bm", name="second")
    await handlers.claim_execution(
        ClaimExecution(execution_id=taken), principal_id=uuid4(), correlation_id=uuid4()
    )

    rows = await _queued(cloned_database)

    assert [row["execution_id"] for row in rows] == [first, second]
