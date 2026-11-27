"""Plans through their handlers: proposed, read, adopted, taken, and advanced in a round.

The deciders and the composing seam are tested on their own. What is left
for the handlers is what those never see: that every operation a plan
cites is loaded and a missing one refused before anything is written,
that adoption and a round both hand the whole plan to one composition,
and that any refusal leaves every stream exactly as it was.

The device-use rule is driven here through the two callers that apply
it, because a rule that holds in the seam holds for a caller only if the
caller hands the seam the operations as folded, declaration included.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.inquiry import InquiryConclusion
from keeper.counsel.aggregates.proposal import (
    PROPOSAL_STREAM_TYPE,
    PlanProposed,
    ProposalCannotBeTakenError,
    ProposalStatus,
    ProposedRun,
    from_stored,
    load_proposal,
)
from keeper.counsel.features.adopt_proposal import AdoptProposal
from keeper.counsel.features.adopt_proposal import bind as bind_adopt
from keeper.counsel.features.answer_inquiry import AnswerInquiry
from keeper.counsel.features.answer_inquiry import bind as bind_answer
from keeper.counsel.features.get_proposal import GetProposal
from keeper.counsel.features.get_proposal import bind as bind_get
from keeper.counsel.features.make_proposal import MakeProposal
from keeper.counsel.features.make_proposal import bind as bind_make
from keeper.counsel.features.propose_plan import ProposePlan
from keeper.counsel.features.propose_plan import bind as bind_propose
from keeper.counsel.features.take_proposal import TakeProposal
from keeper.counsel.features.take_proposal import bind as bind_take
from keeper.execution.aggregates.execution import EXECUTION_STREAM_TYPE, load_execution
from keeper.execution.aggregates.operation import (
    OperationCannotBeCitedError,
    OperationCannotBeComposedError,
    OperationNotFoundError,
    PlaceUse,
)
from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    RunStep,
    load_procedure,
)
from keeper.execution.features.declare_operation_device_use import DeclareOperationDeviceUse
from keeper.execution.features.declare_operation_device_use import bind as bind_declare
from keeper.execution.features.declare_operation_place_use import DeclareOperationPlaceUse
from keeper.execution.features.declare_operation_place_use import bind as bind_declare_places
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.define_procedure import bind as bind_define_procedure
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.execution.features.dispatch_execution import bind as bind_dispatch
from keeper.execution.features.retire_operation import RetireOperation
from keeper.execution.features.retire_operation import bind as bind_retire
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import Allow, AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.pursuit.aggregates.pursuit import (
    Budget,
    BudgetDimension,
    PursuitBeamline,
    PursuitGoal,
    RoundOutcome,
    load_pursuit,
)
from keeper.pursuit.features.close_pursuit_round import ClosePursuitRound
from keeper.pursuit.features.close_pursuit_round import bind as bind_close
from keeper.pursuit.features.open_pursuit_round import OpenPursuitRound
from keeper.pursuit.features.open_pursuit_round import bind as bind_open_round
from keeper.pursuit.features.start_pursuit import StartPursuit
from keeper.pursuit.features.start_pursuit import bind as bind_start
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

pytestmark = pytest.mark.unit

_CLOCK_NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_PURSUIT_SCOPES = ("2bmb:m1", "2bmb:det")


class _FixedClock:
    def now(self) -> datetime:
        return _CLOCK_NOW


class _Uuid4IdGenerator:
    def new_id(self) -> UUID:
        return uuid4()


class _RecordingAuthorize:
    """Allows everything and remembers what it was asked, in order."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str | None]] = []

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
        beamline: str | None = None,
    ) -> AuthzResult:
        _ = (principal_id, surface_id)
        self.asked.append((command_name, beamline))
        return Allow()


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
        beamline: str | None = None,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not granted in this test")


def _kernel(
    *, authz: object | None = None, event_store: InMemoryEventStore | None = None
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(environment="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4IdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store if event_store is not None else InMemoryEventStore(),
    )


async def _an_operation(deps: Kernel, name: str, *, drives_devices: bool | None) -> UUID:
    """An operation declared to name no places, so a pursuit's places never refuse its runs."""
    operation_id = await bind_define_operation(deps)(
        DefineOperation(name=name, parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    if drives_devices is not None:
        await bind_declare(deps)(
            DeclareOperationDeviceUse(operation_id=operation_id, drives_devices=drives_devices),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )
    await bind_declare_places(deps)(
        DeclareOperationPlaceUse(
            operation_id=operation_id,
            place_use=PlaceUse(place_parameters=(), compute_place_parameters=()),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return operation_id


async def _a_plan(deps: Kernel, *operation_ids: UUID, principal_id: UUID | None = None) -> UUID:
    return await bind_propose(deps)(
        ProposePlan(
            runs=tuple(
                ProposedRun(operation_id=operation_id, parameters={"index": index})
                for index, operation_id in enumerate(operation_ids)
            )
        ),
        principal_id=principal_id or uuid4(),
        correlation_id=uuid4(),
    )


async def _collect_and_transfer(deps: Kernel) -> tuple[UUID, UUID]:
    """An operation declared to drive devices and one declared to drive none."""
    collect = await _an_operation(deps, "collect", drives_devices=True)
    transfer = await _an_operation(deps, "transfer", drives_devices=False)
    return collect, transfer


async def _adopt(
    deps: Kernel,
    proposal_id: UUID,
    *,
    scopes: tuple[str, ...] = ("2bmb:det:",),
    drives_no_device: bool = False,
) -> UUID:
    return await bind_adopt(deps)(
        AdoptProposal(
            proposal_id=proposal_id,
            beamline="2-bm",
            scopes=scopes,
            drives_no_device=drives_no_device,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


def _streams(deps: Kernel, stream_type: str) -> list[UUID]:
    """The streams of a type the in-memory store holds, for counting what an append did."""
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)
    return list(store.stream_ids(stream_type))


async def _composed_runs(deps: Kernel, execution_id: UUID) -> list[RunStep]:
    execution = await load_execution(deps.event_store, execution_id)
    assert execution is not None
    procedure = await load_procedure(deps.event_store, execution.procedure_id)
    assert procedure is not None
    steps = [composed.step for composed in procedure.steps]
    assert all(isinstance(step, RunStep) for step in steps)
    return [step for step in steps if isinstance(step, RunStep)]


async def test_proposing_a_plan_writes_one_event_holding_every_run_and_returns_its_id() -> None:
    deps = _kernel()
    collect, transfer = await _collect_and_transfer(deps)
    principal_id = uuid4()

    proposal_id = await _a_plan(deps, collect, transfer, collect, principal_id=principal_id)

    stored, version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert version == 1
    (event,) = [from_stored(row) for row in stored]
    assert isinstance(event, PlanProposed)
    assert event.actor_id == principal_id, "the principal is the proposer, as for one run"
    assert [run.operation_id for run in event.runs] == [collect, transfer, collect]
    assert stored[0].occurred_at == _CLOCK_NOW


async def test_a_plan_citing_an_operation_nobody_defined_is_refused_and_writes_nothing() -> None:
    deps = _kernel()
    collect, _ = await _collect_and_transfer(deps)
    nobody = uuid4()

    with pytest.raises(OperationNotFoundError) as caught:
        await _a_plan(deps, collect, nobody)

    assert caught.value.operation_id == nobody
    assert _streams(deps, PROPOSAL_STREAM_TYPE) == []


async def test_a_plan_citing_a_retired_operation_is_refused_when_proposed() -> None:
    deps = _kernel()
    collect, transfer = await _collect_and_transfer(deps)
    await bind_retire(deps)(
        RetireOperation(operation_id=transfer), principal_id=uuid4(), correlation_id=uuid4()
    )

    with pytest.raises(OperationCannotBeCitedError):
        await _a_plan(deps, collect, transfer)

    assert _streams(deps, PROPOSAL_STREAM_TYPE) == []


async def test_proposing_a_plan_asks_the_gate_about_its_own_command_without_a_beamline() -> None:
    authz = _RecordingAuthorize()
    deps = _kernel(authz=authz)
    collect, transfer = await _collect_and_transfer(deps)

    await _a_plan(deps, collect, transfer)

    assert authz.asked[-1] == ("ProposePlan", None)


async def test_a_caller_refused_a_plan_proposes_nothing() -> None:
    store = InMemoryEventStore()
    collect, transfer = await _collect_and_transfer(_kernel(event_store=store))
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)

    with pytest.raises(UnauthorizedError):
        await _a_plan(deps, collect, transfer)

    assert _streams(deps, PROPOSAL_STREAM_TYPE) == []


async def test_a_plan_reads_back_as_a_proposal_holding_its_runs() -> None:
    deps = _kernel()
    collect, transfer = await _collect_and_transfer(deps)
    proposal_id = await _a_plan(deps, collect, transfer)

    proposal = await bind_get(deps)(
        GetProposal(proposal_id=proposal_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert proposal.runs == (
        ProposedRun(operation_id=collect, parameters={"index": 0}),
        ProposedRun(operation_id=transfer, parameters={"index": 1}),
    )
    assert proposal.sole_run is None
    assert proposal.status is ProposalStatus.OPEN


async def test_adopting_a_plan_dispatches_one_execution_with_a_step_per_run_in_order() -> None:
    deps = _kernel()
    collect, transfer = await _collect_and_transfer(deps)
    proposal_id = await _a_plan(deps, collect, transfer, collect)

    execution_id = await _adopt(deps, proposal_id)

    execution = await load_execution(deps.event_store, execution_id)
    assert execution is not None
    assert len(execution.steps) == 3
    runs = await _composed_runs(deps, execution_id)
    assert [run.operation_id for run in runs] == [collect, transfer, collect]
    assert [run.parameters for run in runs] == [{"index": 0}, {"index": 1}, {"index": 2}]
    assert len(_streams(deps, EXECUTION_STREAM_TYPE)) == 1
    assert len(_streams(deps, PROCEDURE_STREAM_TYPE)) == 1


async def test_adopting_a_plan_claims_devices_only_for_the_runs_that_drive_them() -> None:
    deps = _kernel()
    collect, transfer = await _collect_and_transfer(deps)
    proposal_id = await _a_plan(deps, collect, transfer)

    execution_id = await _adopt(deps, proposal_id, scopes=("2bmb:det:", "2bmb:m1"))

    assert [
        (run.scopes, run.drives_no_device) for run in await _composed_runs(deps, execution_id)
    ] == [
        (("2bmb:det:", "2bmb:m1"), False),
        ((), True),
    ]


async def test_an_adopted_plan_points_at_the_first_of_its_steps() -> None:
    deps = _kernel()
    collect, transfer = await _collect_and_transfer(deps)
    proposal_id = await _a_plan(deps, collect, transfer)

    execution_id = await _adopt(deps, proposal_id)

    proposal = await load_proposal(deps.event_store, proposal_id)
    execution = await load_execution(deps.event_store, execution_id)
    assert proposal is not None
    assert execution is not None
    assert proposal.status is ProposalStatus.ADOPTED
    assert (proposal.execution_id, proposal.step_id) == (execution_id, execution.steps[0].id)


async def test_a_plan_whose_runs_all_drive_nothing_needs_no_devices_named() -> None:
    deps = _kernel()
    transfer = await _an_operation(deps, "transfer", drives_devices=False)
    process = await _an_operation(deps, "process", drives_devices=False)
    proposal_id = await _a_plan(deps, transfer, process, transfer)

    execution_id = await _adopt(deps, proposal_id, scopes=())

    assert {run.drives_no_device for run in await _composed_runs(deps, execution_id)} == {True}


async def test_adopting_a_plan_citing_an_undeclared_operation_is_refused_and_writes_nothing() -> (
    None
):
    deps = _kernel()
    collect, _ = await _collect_and_transfer(deps)
    undeclared = await _an_operation(deps, "transfer", drives_devices=None)
    proposal_id = await _a_plan(deps, collect, undeclared)

    with pytest.raises(OperationCannotBeComposedError) as caught:
        await _adopt(deps, proposal_id)

    assert (caught.value.operation_id, caught.value.index) == (undeclared, 1)
    proposal = await load_proposal(deps.event_store, proposal_id)
    assert proposal is not None
    assert proposal.status is ProposalStatus.OPEN
    assert _streams(deps, EXECUTION_STREAM_TYPE) == []
    assert _streams(deps, PROCEDURE_STREAM_TYPE) == []


async def test_a_plan_refused_for_an_undeclared_operation_is_adopted_once_it_is_declared() -> None:
    """Device use is read when the plan is adopted, not when it was proposed."""
    deps = _kernel()
    collect, _ = await _collect_and_transfer(deps)
    undeclared = await _an_operation(deps, "transfer", drives_devices=None)
    proposal_id = await _a_plan(deps, collect, undeclared)
    with pytest.raises(OperationCannotBeComposedError):
        await _adopt(deps, proposal_id)

    await bind_declare(deps)(
        DeclareOperationDeviceUse(operation_id=undeclared, drives_devices=False),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution_id = await _adopt(deps, proposal_id)

    assert [run.drives_no_device for run in await _composed_runs(deps, execution_id)] == [
        False,
        True,
    ]


async def test_saying_a_plan_drives_nothing_is_refused_when_one_of_its_runs_does() -> None:
    deps = _kernel()
    collect, transfer = await _collect_and_transfer(deps)
    proposal_id = await _a_plan(deps, transfer, collect)

    with pytest.raises(OperationCannotBeComposedError, match="Run 1") as caught:
        await _adopt(deps, proposal_id, scopes=(), drives_no_device=True)

    assert (caught.value.operation_id, caught.value.drives_devices) == (collect, True)
    assert _streams(deps, EXECUTION_STREAM_TYPE) == []


async def test_one_run_of_an_operation_declared_to_drive_nothing_claims_none_at_adoption() -> None:
    """The declaration applies to a proposal of one run too, whatever the adopter named."""
    deps = _kernel()
    transfer = await _an_operation(deps, "transfer", drives_devices=False)
    proposal_id = await bind_make(deps)(
        MakeProposal(operation_id=transfer, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    execution_id = await _adopt(deps, proposal_id, scopes=("2bmb:det:",))

    assert [
        (run.scopes, run.drives_no_device) for run in await _composed_runs(deps, execution_id)
    ] == [((), True)]


async def test_one_run_of_an_undeclared_operation_is_adopted_exactly_as_before() -> None:
    deps = _kernel()
    count = await _an_operation(deps, "count", drives_devices=None)
    proposal_id = await bind_make(deps)(
        MakeProposal(operation_id=count, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    execution_id = await _adopt(deps, proposal_id, scopes=("2bmb:det:",))

    assert [
        (run.scopes, run.drives_no_device) for run in await _composed_runs(deps, execution_id)
    ] == [(("2bmb:det:",), False)]


async def test_taking_a_plan_of_several_runs_is_refused_and_writes_nothing() -> None:
    deps = _kernel()
    collect, transfer = await _collect_and_transfer(deps)
    proposal_id = await _a_plan(deps, collect, transfer)
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(
            name="collect",
            beamline="2-bm",
            steps=(RunStep(operation_id=collect, parameters={}, scopes=("2bmb:det:",)),),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution_id = await bind_dispatch(deps)(
        DispatchExecution(procedure_id=procedure_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    execution = await load_execution(deps.event_store, execution_id)
    assert execution is not None

    with pytest.raises(ProposalCannotBeTakenError, match="plan of 2 runs"):
        await bind_take(deps)(
            TakeProposal(
                proposal_id=proposal_id, execution_id=execution_id, step_id=execution.steps[0].id
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    _rows, version = await deps.event_store.load(PROPOSAL_STREAM_TYPE, proposal_id)
    assert version == 1


async def _a_round_answered_with(deps: Kernel, proposal_id: UUID) -> UUID:
    """A running pursuit with one round whose inquiry proposed this proposal."""
    pursuit_id = await bind_start(deps)(
        StartPursuit(
            goal=PursuitGoal("reconstruct what the station collects"),
            beamline=PursuitBeamline("2-bm"),
            scopes=_PURSUIT_SCOPES,
            budget=Budget({BudgetDimension.ROUNDS: 8}),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    first = await _an_operation(deps, "align", drives_devices=True)
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(
            name="align",
            beamline="2-bm",
            steps=(RunStep(operation_id=first, parameters={}, scopes=("2bmb:m1",)),),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution_id = await bind_dispatch(deps)(
        DispatchExecution(procedure_id=procedure_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    inquiry_id = await bind_open_round(deps)(
        OpenPursuitRound(pursuit_id=pursuit_id, execution_id=execution_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    await bind_answer(deps)(
        AnswerInquiry(
            inquiry_id=inquiry_id,
            conclusion=InquiryConclusion.PROPOSE,
            observed_step_count=1,
            execution_ended=True,
            proposal_id=proposal_id,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return pursuit_id


async def _close(deps: Kernel, pursuit_id: UUID) -> Any:
    return await bind_close(deps)(
        ClosePursuitRound(pursuit_id=pursuit_id, round_index=0),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_a_round_advancing_on_a_plan_dispatches_it_whole_under_the_pursuits_scopes() -> None:
    deps = _kernel()
    collect, transfer = await _collect_and_transfer(deps)
    proposal_id = await _a_plan(deps, collect, transfer)
    pursuit_id = await _a_round_answered_with(deps, proposal_id)

    closed = await _close(deps, pursuit_id)

    assert closed.outcome is RoundOutcome.ADVANCED
    assert [
        (run.operation_id, run.scopes, run.drives_no_device)
        for run in await _composed_runs(deps, closed.dispatched_id)
    ] == [(collect, _PURSUIT_SCOPES, False), (transfer, (), True)]
    proposal = await load_proposal(deps.event_store, proposal_id)
    assert proposal is not None
    assert proposal.status is ProposalStatus.ADOPTED


async def test_a_round_on_a_plan_citing_an_undeclared_operation_stays_open_and_writes_nothing() -> (
    None
):
    deps = _kernel()
    collect, _ = await _collect_and_transfer(deps)
    undeclared = await _an_operation(deps, "transfer", drives_devices=None)
    proposal_id = await _a_plan(deps, collect, undeclared)
    pursuit_id = await _a_round_answered_with(deps, proposal_id)
    executions_before = len(_streams(deps, EXECUTION_STREAM_TYPE))

    with pytest.raises(OperationCannotBeComposedError):
        await _close(deps, pursuit_id)

    pursuit = await load_pursuit(deps.event_store, pursuit_id)
    proposal = await load_proposal(deps.event_store, proposal_id)
    assert pursuit is not None
    assert proposal is not None
    assert pursuit.rounds[0].is_open
    assert proposal.status is ProposalStatus.OPEN
    assert len(_streams(deps, EXECUTION_STREAM_TYPE)) == executions_before
