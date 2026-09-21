"""The Counsel slices, driven end to end against a real Postgres.

Every other test of this context runs on `InMemoryEventStore`, which
hands back the very objects it was given. Three things here are not
proven by that.

The parameters are the first. In state they are a document; in a row
they are a JSONB value that went out through a serialiser and came back
through a codec. A proposal that folds correctly from a dict it never
serialised proves nothing about the one a deployed system reads back,
and those values are most of what a proposal says.

The two cross-context reads are the second. Making a proposal loads a
plan and taking one loads a run, both out of different stream types in
the same table. In memory those are dictionary keys; in Postgres they
are queries that have to name the right stream type, and a query naming
the wrong one finds nothing and reports a plan that exists as missing.

The second event on a stream is the third, and it is what this context
has that Custody does not. `take_proposal` appends at a version it read,
so the append path that matters is the one with a non-zero expected
version behind it.

The queries below spell `"Proposal"` as a literal rather than using
`PROPOSAL_STREAM_TYPE`. That is the only independent side these tests
have: a query built from the writer's own constant agrees with the
writer however wrong the constant is.

The handlers come from `wire_counsel`, not from `bind`, so these go
through the same composition the application boots: tracing and the
idempotency wrapper.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import asyncpg
import pytest

from aroc.counsel import wire_counsel
from aroc.counsel.aggregates.proposal import (
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
    load_proposal,
)
from aroc.counsel.features.get_proposal import GetProposal
from aroc.counsel.features.make_proposal import MakeProposal
from aroc.counsel.features.take_proposal import TakeProposal
from aroc.execution import wire_execution
from aroc.execution.aggregates.plan import PlanNotFoundError
from aroc.execution.aggregates.run import RunNotFoundError
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.report_run import ReportRun
from aroc.infrastructure.deps import make_postgres_kernel
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import AllowAllAuthorize
from aroc.infrastructure.ports.clock import SystemClock
from aroc.infrastructure.ports.id_generator import UUIDv7Generator
from aroc.infrastructure.settings import Settings
from aroc.shared.identifier import Identifier

pytestmark = pytest.mark.integration

_REPORTED = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_PARAMETERS: dict[str, Any] = {
    "exposure_time_s": 0.1,
    "num_projections": 1500,
    "sample": {"name": "shale-04", "tags": ["dry", "reference"]},
}


@pytest.fixture
def kernel(db_pool: asyncpg.Pool) -> Kernel:
    """A kernel over the real pool, built the way the application builds one."""
    return make_postgres_kernel(
        db_pool,
        settings=Settings(app_env="test"),
        clock=SystemClock(),
        id_generator=UUIDv7Generator(),
        authz=AllowAllAuthorize(),
    )


async def _a_plan(deps: Kernel) -> UUID:
    return await wire_execution(deps).define_plan(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_run_of(deps: Kernel, plan_id: UUID) -> UUID:
    return await wire_execution(deps).report_run(
        ReportRun(
            plan_id=plan_id,
            parameters={},
            external_ref=Identifier(scheme="bluesky-run-uid", value=str(uuid4())),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_a_proposal_reads_back_through_a_real_round_trip(kernel: Kernel) -> None:
    counsel = wire_counsel(kernel)
    principal_id = uuid4()
    plan_id = await _a_plan(kernel)

    proposal_id = await counsel.make_proposal(
        MakeProposal(plan_id=plan_id, parameters=dict(_PARAMETERS)),
        principal_id=principal_id,
        correlation_id=uuid4(),
    )
    proposal = await counsel.get_proposal(
        GetProposal(proposal_id=proposal_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert (proposal.id, proposal.actor_id, proposal.plan_id) == (
        proposal_id,
        principal_id,
        plan_id,
    )
    assert proposal.run_id is None


async def test_nested_parameters_survive_the_jsonb_round_trip(
    kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """A document with a nested object and a list, not just flat scalars."""
    counsel = wire_counsel(kernel)

    proposal_id = await counsel.make_proposal(
        MakeProposal(plan_id=await _a_plan(kernel), parameters=dict(_PARAMETERS)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    proposal = await load_proposal(kernel.event_store, proposal_id)
    assert proposal is not None
    assert proposal.parameters == _PARAMETERS

    row = await db_pool.fetchrow(
        "SELECT event_type FROM events WHERE stream_type = 'Proposal' AND stream_id = $1",
        proposal_id,
    )
    assert row is not None
    assert row["event_type"] == "ProposalMade"


async def test_the_plan_a_proposal_names_is_found_across_the_stream_types(
    kernel: Kernel,
) -> None:
    """Plan and Proposal share a table, so the query has to name the right type."""
    counsel = wire_counsel(kernel)

    proposal_id = await counsel.make_proposal(
        MakeProposal(plan_id=await _a_plan(kernel), parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert proposal_id is not None


async def test_naming_a_plan_that_does_not_exist_writes_nothing(
    kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    counsel = wire_counsel(kernel)

    with pytest.raises(PlanNotFoundError):
        await counsel.make_proposal(
            MakeProposal(plan_id=uuid4(), parameters={}),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    count = await db_pool.fetchval("SELECT count(*) FROM events WHERE stream_type = 'Proposal'")
    assert count == 0


async def test_taking_appends_a_second_event_at_the_version_it_read(
    kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    counsel = wire_counsel(kernel)
    plan_id = await _a_plan(kernel)
    run_id = await _a_run_of(kernel, plan_id)
    proposal_id = await counsel.make_proposal(
        MakeProposal(plan_id=plan_id, parameters=dict(_PARAMETERS)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await counsel.take_proposal(
        TakeProposal(proposal_id=proposal_id, run_id=run_id, occurred_at=_REPORTED),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows = await db_pool.fetch(
        "SELECT event_type, version FROM events "
        "WHERE stream_type = 'Proposal' AND stream_id = $1 ORDER BY version",
        proposal_id,
    )
    assert [(row["event_type"], row["version"]) for row in rows] == [
        ("ProposalMade", 1),
        ("ProposalTaken", 2),
    ]


async def test_a_reported_take_time_is_stored_as_the_instant_it_names(
    kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    counsel = wire_counsel(kernel)
    plan_id = await _a_plan(kernel)
    run_id = await _a_run_of(kernel, plan_id)
    proposal_id = await counsel.make_proposal(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await counsel.take_proposal(
        TakeProposal(proposal_id=proposal_id, run_id=run_id, occurred_at=_REPORTED),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    occurred_at = await db_pool.fetchval(
        "SELECT occurred_at FROM events "
        "WHERE stream_type = 'Proposal' AND stream_id = $1 AND event_type = 'ProposalTaken'",
        proposal_id,
    )
    assert occurred_at == _REPORTED


async def test_taking_with_a_run_that_does_not_exist_writes_nothing(
    kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """The run lives in another stream type, so this is a real cross-type miss."""
    counsel = wire_counsel(kernel)
    proposal_id = await counsel.make_proposal(
        MakeProposal(plan_id=await _a_plan(kernel), parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    with pytest.raises(RunNotFoundError):
        await counsel.take_proposal(
            TakeProposal(proposal_id=proposal_id, run_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    count = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_type = 'Proposal' AND stream_id = $1",
        proposal_id,
    )
    assert count == 1


async def test_taking_one_twice_leaves_the_first_run_on_the_record(
    kernel: Kernel,
) -> None:
    counsel = wire_counsel(kernel)
    plan_id = await _a_plan(kernel)
    first_run = await _a_run_of(kernel, plan_id)
    second_run = await _a_run_of(kernel, plan_id)
    proposal_id = await counsel.make_proposal(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await counsel.take_proposal(
        TakeProposal(proposal_id=proposal_id, run_id=first_run),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    with pytest.raises(ProposalCannotBeTakenError):
        await counsel.take_proposal(
            TakeProposal(proposal_id=proposal_id, run_id=second_run),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    proposal = await load_proposal(kernel.event_store, proposal_id)
    assert proposal is not None
    assert proposal.run_id == first_run


async def test_reading_a_proposal_that_was_never_made_is_refused(kernel: Kernel) -> None:
    counsel = wire_counsel(kernel)

    with pytest.raises(ProposalNotFoundError):
        await counsel.get_proposal(
            GetProposal(proposal_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_replayed_key_returns_the_first_proposal_rather_than_a_second(
    kernel: Kernel, db_pool: asyncpg.Pool
) -> None:
    """Against the real key store, not a dictionary."""
    counsel = wire_counsel(kernel)
    plan_id = await _a_plan(kernel)
    principal_id = uuid4()
    command = MakeProposal(plan_id=plan_id, parameters=dict(_PARAMETERS))

    first = await counsel.make_proposal(
        command,
        principal_id=principal_id,
        correlation_id=uuid4(),
        idempotency_key="agent-turn-41",
    )
    second = await counsel.make_proposal(
        command,
        principal_id=principal_id,
        correlation_id=uuid4(),
        idempotency_key="agent-turn-41",
    )

    assert first == second
    count = await db_pool.fetchval(
        "SELECT count(*) FROM events WHERE stream_type = 'Proposal' AND stream_id = $1",
        first,
    )
    assert count == 1
