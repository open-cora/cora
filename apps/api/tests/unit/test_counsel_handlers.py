"""The three Counsel handlers, against in-process stores.

One file for three handlers, because what is worth testing about them is
shared: each reads across into Execution, and the cases that matter are
the ones about that read and about who the record says proposed.

The split between this file and the two decider files is the usual one.
A decider is handed its inputs; a handler is what fetches them, refuses
a sibling that is not there, and picks which moment to stamp.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from aroc.counsel.aggregates.proposal import (
    PROPOSAL_STREAM_TYPE,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
    load_proposal,
)
from aroc.counsel.errors import UnauthorizedError
from aroc.counsel.features.get_proposal import GetProposal
from aroc.counsel.features.get_proposal import bind as bind_get
from aroc.counsel.features.make_proposal import MakeProposal
from aroc.counsel.features.make_proposal import bind as bind_make
from aroc.counsel.features.take_proposal import TakeProposal
from aroc.counsel.features.take_proposal import bind as bind_take
from aroc.execution.aggregates.plan import PlanNotFoundError
from aroc.execution.aggregates.run import RunNotFoundError
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.define_plan import bind as bind_define_plan
from aroc.execution.features.report_run import ReportRun
from aroc.execution.features.report_run import bind as bind_report_run
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.deps import make_inmemory_kernel
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import AllowAllAuthorize, Deny
from aroc.infrastructure.ports.authorize import AuthzResult
from aroc.infrastructure.settings import Settings
from aroc.shared.identifier import Identifier
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_CLOCK_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
"""What the clock says, deliberately not the time any caller reports."""
_REPORTED = datetime(2026, 9, 18, 6, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_PARAMETERS: dict[str, Any] = {"exposure_time_s": 0.1}


class _FixedClock:
    def now(self) -> datetime:
        return _CLOCK_NOW


class _Uuid4IdGenerator:
    def new_id(self) -> UUID:
        return uuid4()


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not granted in this test")


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4IdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _a_plan(deps: Kernel) -> UUID:
    return await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_run_of(deps: Kernel, plan_id: UUID) -> UUID:
    return await bind_report_run(deps)(
        ReportRun(
            plan_id=plan_id,
            parameters=dict(_PARAMETERS),
            external_ref=Identifier(scheme="bluesky-uid", value=str(uuid4())),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_making_a_proposal_writes_one_event_and_returns_its_id() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)

    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters=dict(_PARAMETERS)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert [row.event_type for row in stored] == ["ProposalMade"]


async def test_the_principal_becomes_the_proposer_on_the_record() -> None:
    """The one place this handler does more than plumb."""
    deps = _kernel()
    plan_id = await _a_plan(deps)
    principal_id = uuid4()

    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=principal_id,
        correlation_id=uuid4(),
    )

    proposal = await load_proposal(deps.event_store, proposal_id)
    assert proposal is not None
    assert proposal.actor_id == principal_id


async def test_a_proposal_is_stamped_with_the_clock_and_nothing_else() -> None:
    """R8 in the wiring: there is no reported time for a caller to send."""
    deps = _kernel()
    plan_id = await _a_plan(deps)

    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert stored[0].occurred_at == _CLOCK_NOW


async def test_proposing_against_a_plan_that_is_not_there_is_refused() -> None:
    deps = _kernel()

    with pytest.raises(PlanNotFoundError):
        await bind_make(deps)(
            MakeProposal(plan_id=uuid4(), parameters={}),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_denied_caller_makes_no_proposal() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())
    plan_id = await _a_plan(_kernel())

    with pytest.raises(UnauthorizedError):
        await bind_make(deps)(
            MakeProposal(plan_id=plan_id, parameters={}),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_taking_a_proposal_appends_to_the_stream_the_genesis_opened() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    run_id = await _a_run_of(deps, plan_id)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters=dict(_PARAMETERS)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await bind_take(deps)(
        TakeProposal(proposal_id=proposal_id, run_id=run_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert [row.event_type for row in stored] == ["ProposalMade", "ProposalTaken"]


async def test_a_taken_proposal_reads_back_with_its_run_recorded() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    run_id = await _a_run_of(deps, plan_id)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await bind_take(deps)(
        TakeProposal(proposal_id=proposal_id, run_id=run_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    proposal = await load_proposal(deps.event_store, proposal_id)
    assert proposal is not None
    assert proposal.run_id == run_id


async def test_a_reported_time_beats_the_clock_when_a_take_carries_one() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    run_id = await _a_run_of(deps, plan_id)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await bind_take(deps)(
        TakeProposal(proposal_id=proposal_id, run_id=run_id, occurred_at=_REPORTED),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert (stored[0].occurred_at, stored[1].occurred_at) == (_CLOCK_NOW, _REPORTED)


async def test_taking_with_a_run_that_is_not_there_is_the_handlers_refusal() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    with pytest.raises(RunNotFoundError):
        await bind_take(deps)(
            TakeProposal(proposal_id=proposal_id, run_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert len(stored) == 1


async def test_taking_with_a_run_of_another_plan_writes_nothing() -> None:
    deps = _kernel()
    proposed_plan = await _a_plan(deps)
    other_plan = await _a_plan(deps)
    other_run = await _a_run_of(deps, other_plan)
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=proposed_plan, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    with pytest.raises(ProposalCannotBeTakenError):
        await bind_take(deps)(
            TakeProposal(proposal_id=proposal_id, run_id=other_run),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    stored, _version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert len(stored) == 1


async def test_reading_a_proposal_that_was_never_made_is_refused() -> None:
    deps = _kernel()

    with pytest.raises(ProposalNotFoundError):
        await bind_get(deps)(
            GetProposal(proposal_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_reading_one_back_gives_what_was_proposed() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    principal_id = uuid4()
    proposal_id = await bind_make(deps)(
        MakeProposal(plan_id=plan_id, parameters=dict(_PARAMETERS)),
        principal_id=principal_id,
        correlation_id=uuid4(),
    )

    proposal = await bind_get(deps)(
        GetProposal(proposal_id=proposal_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert (proposal.id, proposal.actor_id, proposal.plan_id) == (
        proposal_id,
        principal_id,
        plan_id,
    )
    assert proposal.parameters == _PARAMETERS
    assert proposal.run_id is None


async def test_a_denied_caller_cannot_read_a_proposal() -> None:
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await bind_get(deps)(
            GetProposal(proposal_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )
