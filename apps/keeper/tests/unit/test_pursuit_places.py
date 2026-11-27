"""A pursuit's places, from the start that states them to the close that reads them.

The handlers, through the in-memory kernel, because the rule lives in the
seam between two contexts: a pursuit says which places it authorizes, an
operation says which of a run's values are places, and only a close that
loads both can tell whether a plan stays inside what was authorized.

The plan walked here is the loop the facility wants, a collection, the
move of its data to a computing facility, the processing there and the
move of the result back, so the refusals below are each one place taken
away from a plan that otherwise closes.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.inquiry import InquiryConclusion
from keeper.counsel.aggregates.proposal import ProposalStatus, ProposedRun, load_proposal
from keeper.counsel.features.answer_inquiry import AnswerInquiry
from keeper.counsel.features.answer_inquiry import bind as bind_answer
from keeper.counsel.features.propose_plan import ProposePlan
from keeper.counsel.features.propose_plan import bind as bind_propose
from keeper.execution.aggregates.execution import EXECUTION_STREAM_TYPE, load_execution
from keeper.execution.aggregates.operation import OperationCannotBeCitedError, PlaceUse
from keeper.execution.aggregates.procedure import SetStep
from keeper.execution.features.declare_operation_device_use import DeclareOperationDeviceUse
from keeper.execution.features.declare_operation_device_use import bind as bind_declare_devices
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
from keeper.infrastructure.ports import AllowAllAuthorize
from keeper.infrastructure.settings import Settings
from keeper.pursuit.aggregates.pursuit import (
    PURSUIT_STREAM_TYPE,
    Budget,
    BudgetDimension,
    PursuitBeamline,
    PursuitGoal,
    PursuitRoundCannotBeClosedError,
    RoundOutcome,
    load_pursuit,
)
from keeper.pursuit.features.close_pursuit_round import ClosePursuitRound
from keeper.pursuit.features.close_pursuit_round import bind as bind_close
from keeper.pursuit.features.open_pursuit_round import OpenPursuitRound
from keeper.pursuit.features.open_pursuit_round import bind as bind_open_round
from keeper.pursuit.features.start_pursuit import StartPursuit
from keeper.pursuit.features.start_pursuit import bind as bind_start

pytestmark = pytest.mark.unit

_CLOCK_NOW = datetime(2026, 11, 27, 14, 0, tzinfo=UTC)
_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_SCOPES = ("19bm:det:", "19bm:rot:")


class _FixedClock:
    def now(self) -> datetime:
        return _CLOCK_NOW


class _Uuid4IdGenerator:
    def new_id(self) -> UUID:
        return uuid4()


def _kernel() -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(environment="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4IdGenerator(),
        authz=AllowAllAuthorize(),
        event_store=InMemoryEventStore(),
    )


def _schema(*names: str) -> dict[str, Any]:
    return {
        "$schema": _DRAFT,
        "type": "object",
        "properties": {name: {"type": "string"} for name in names},
    }


async def _an_operation(
    deps: Kernel,
    name: str,
    parameters: tuple[str, ...],
    *,
    drives_devices: bool,
    place_use: PlaceUse | None,
) -> UUID:
    """An operation with its device use declared and, unless None, its place use."""
    operation_id = await bind_define_operation(deps)(
        DefineOperation(name=name, parameters_schema=_schema(*parameters)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    await bind_declare_devices(deps)(
        DeclareOperationDeviceUse(operation_id=operation_id, drives_devices=drives_devices),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    if place_use is not None:
        await bind_declare_places(deps)(
            DeclareOperationPlaceUse(operation_id=operation_id, place_use=place_use),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )
    return operation_id


class _Register:
    """The three operations of the loop, declared the way the facility's register declares them."""

    def __init__(self, collect: UUID, move: UUID, process: UUID) -> None:
        self.collect = collect
        self.move = move
        self.process = process


async def _the_register(deps: Kernel) -> _Register:
    return _Register(
        collect=await _an_operation(
            deps,
            "collect",
            ("at", "output"),
            drives_devices=True,
            place_use=PlaceUse(place_parameters=("at",), compute_place_parameters=()),
        ),
        move=await _an_operation(
            deps,
            "move",
            ("path", "from", "to"),
            drives_devices=False,
            place_use=PlaceUse(place_parameters=("from", "to"), compute_place_parameters=()),
        ),
        process=await _an_operation(
            deps,
            "process",
            ("at", "input", "output"),
            drives_devices=False,
            place_use=PlaceUse(place_parameters=(), compute_place_parameters=("at",)),
        ),
    )


def _the_loop(register: _Register, *, away: str = "alcf") -> list[tuple[UUID, dict[str, Any]]]:
    """Collect here, move away, process there, move the result home."""
    return [
        (register.collect, {"at": "19-bm", "output": "scans/0006/"}),
        (register.move, {"path": "scans/0006/", "from": "19-bm", "to": away}),
        (register.process, {"at": away, "input": "scans/0006/", "output": "recon/0006/"}),
        (register.move, {"path": "recon/0006/", "from": away, "to": "19-bm"}),
    ]


async def _a_pursuit(
    deps: Kernel, *, places: tuple[str, ...] = (), compute_places: tuple[str, ...] = ()
) -> UUID:
    return await bind_start(deps)(
        StartPursuit(
            goal=PursuitGoal("reconstruct what the station collects"),
            beamline=PursuitBeamline("19-bm"),
            scopes=_SCOPES,
            budget=Budget({BudgetDimension.ROUNDS: 8, BudgetDimension.COMPUTE_SECONDS: 7200}),
            places=places,
            compute_places=compute_places,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_round_proposing(
    deps: Kernel, pursuit_id: UUID, runs: list[tuple[UUID, dict[str, Any]]]
) -> UUID:
    """Open a round about a real execution, and answer it with a plan of these runs."""
    procedure_id = await bind_define_procedure(deps)(
        DefineProcedure(
            name="align", beamline="19-bm", steps=(SetStep(record="19bm:rot:m1", to=0.0),)
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    execution_id = await bind_dispatch(deps)(
        DispatchExecution(procedure_id=procedure_id), principal_id=uuid4(), correlation_id=uuid4()
    )
    proposal_id = await bind_propose(deps)(
        ProposePlan(
            runs=tuple(
                ProposedRun(operation_id=operation_id, parameters=parameters)
                for operation_id, parameters in runs
            )
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
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
    return proposal_id


async def _close(deps: Kernel, pursuit_id: UUID) -> Any:
    return await bind_close(deps)(
        ClosePursuitRound(pursuit_id=pursuit_id, round_index=0),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


def _executions(deps: Kernel) -> int:
    """How many executions the in-memory store holds, for telling whether a close dispatched."""
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)
    return len(store.stream_ids(EXECUTION_STREAM_TYPE))


async def _refused_and_untouched(deps: Kernel, pursuit_id: UUID, proposal_id: UUID) -> str:
    """Close, expect the refusal, and check nothing was written by the attempt."""
    executions_before = _executions(deps)

    with pytest.raises(PursuitRoundCannotBeClosedError) as refused:
        await _close(deps, pursuit_id)

    pursuit = await load_pursuit(deps.event_store, pursuit_id)
    proposal = await load_proposal(deps.event_store, proposal_id)
    assert pursuit is not None
    assert proposal is not None
    assert pursuit.rounds[0].is_open, "a refused close leaves the round open"
    assert proposal.status is ProposalStatus.OPEN
    assert _executions(deps) == executions_before
    return str(refused.value)


async def test_starting_with_places_writes_them_beside_the_genesis_in_one_append() -> None:
    deps = _kernel()

    pursuit_id = await _a_pursuit(deps, places=("19-bm", "alcf"), compute_places=("alcf",))

    stored, version = await deps.event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    assert [row.event_type for row in stored] == ["PursuitStarted", "PursuitPlacesAuthorized"]
    assert version == 2
    assert {row.occurred_at for row in stored} == {_CLOCK_NOW}
    pursuit = await load_pursuit(deps.event_store, pursuit_id)
    assert pursuit is not None
    assert (pursuit.places, pursuit.compute_places) == (("19-bm", "alcf"), ("alcf",))


async def test_starting_without_places_writes_the_genesis_alone() -> None:
    deps = _kernel()

    pursuit_id = await _a_pursuit(deps)

    stored, _version = await deps.event_store.load(PURSUIT_STREAM_TYPE, pursuit_id)
    assert [row.event_type for row in stored] == ["PursuitStarted"]


async def test_starting_with_compute_places_alone_still_writes_them() -> None:
    deps = _kernel()

    pursuit_id = await _a_pursuit(deps, compute_places=("alcf",))

    pursuit = await load_pursuit(deps.event_store, pursuit_id)
    assert pursuit is not None
    assert (pursuit.places, pursuit.compute_places) == ((), ("alcf",))


async def test_a_round_on_the_whole_loop_closes_when_every_place_is_authorized() -> None:
    deps = _kernel()
    register = await _the_register(deps)
    pursuit_id = await _a_pursuit(deps, places=("19-bm", "alcf"), compute_places=("alcf",))
    await _a_round_proposing(deps, pursuit_id, _the_loop(register))

    closed = await _close(deps, pursuit_id)

    assert closed.outcome is RoundOutcome.ADVANCED
    dispatched = await load_execution(deps.event_store, closed.dispatched_id)
    assert dispatched is not None
    assert len(dispatched.steps) == 4


async def test_a_move_to_a_place_the_pursuit_does_not_authorize_refuses_the_close() -> None:
    deps = _kernel()
    register = await _the_register(deps)
    pursuit_id = await _a_pursuit(deps, places=("19-bm", "alcf"), compute_places=("alcf",))
    loop = _the_loop(register)
    loop[3] = (register.move, {"path": "recon/0006/", "from": "alcf", "to": "nersc"})
    proposal_id = await _a_round_proposing(deps, pursuit_id, loop)

    said = await _refused_and_untouched(deps, pursuit_id, proposal_id)

    assert "run 3 names 'nersc' in 'to'" in said


async def test_a_process_at_a_compute_place_the_pursuit_does_not_authorize_is_refused() -> None:
    deps = _kernel()
    register = await _the_register(deps)
    pursuit_id = await _a_pursuit(deps, places=("19-bm", "alcf"))
    proposal_id = await _a_round_proposing(deps, pursuit_id, _the_loop(register))

    said = await _refused_and_untouched(deps, pursuit_id, proposal_id)

    assert "run 2 processes at 'alcf'" in said
    assert "compute place" in said


async def test_a_compute_place_does_not_let_data_move_to_it() -> None:
    """The two lists answer two questions. Processing somewhere is not
    leave to carry a station's data there."""
    deps = _kernel()
    register = await _the_register(deps)
    pursuit_id = await _a_pursuit(deps, places=("19-bm",), compute_places=("alcf",))
    proposal_id = await _a_round_proposing(deps, pursuit_id, _the_loop(register))

    said = await _refused_and_untouched(deps, pursuit_id, proposal_id)

    assert "run 1 names 'alcf' in 'to'" in said


async def test_a_collection_landing_somewhere_unauthorized_is_refused_like_a_move() -> None:
    deps = _kernel()
    register = await _the_register(deps)
    pursuit_id = await _a_pursuit(deps, places=("alcf",), compute_places=("alcf",))
    proposal_id = await _a_round_proposing(
        deps, pursuit_id, [(register.collect, {"at": "19-bm", "output": "scans/0006/"})]
    )

    said = await _refused_and_untouched(deps, pursuit_id, proposal_id)

    assert "run 0 names '19-bm' in 'at'" in said


async def test_a_pursuit_naming_no_places_refuses_a_move() -> None:
    deps = _kernel()
    register = await _the_register(deps)
    pursuit_id = await _a_pursuit(deps)
    proposal_id = await _a_round_proposing(
        deps,
        pursuit_id,
        [(register.move, {"path": "scans/0006/", "from": "19-bm", "to": "alcf"})],
    )

    said = await _refused_and_untouched(deps, pursuit_id, proposal_id)

    assert "run 0 names '19-bm' in 'from'" in said


async def test_a_pursuit_naming_no_places_still_closes_on_a_collection_that_names_none() -> None:
    """A parameter a run leaves out names nothing, so a collection that does
    not say where it lands is checked for its devices alone."""
    deps = _kernel()
    register = await _the_register(deps)
    pursuit_id = await _a_pursuit(deps)
    await _a_round_proposing(deps, pursuit_id, [(register.collect, {})])

    closed = await _close(deps, pursuit_id)

    assert closed.outcome is RoundOutcome.ADVANCED


async def test_a_run_of_an_operation_nobody_declared_place_use_for_refuses_the_close() -> None:
    """Undeclared is not a quiet none: a move nobody can read the ends of
    could go anywhere a conductor routes."""
    deps = _kernel()
    undeclared = await _an_operation(
        deps, "move", ("path", "from", "to"), drives_devices=False, place_use=None
    )
    pursuit_id = await _a_pursuit(deps, places=("19-bm", "alcf"))
    proposal_id = await _a_round_proposing(
        deps, pursuit_id, [(undeclared, {"path": "scans/", "from": "19-bm", "to": "alcf"})]
    )

    said = await _refused_and_untouched(deps, pursuit_id, proposal_id)

    assert f"run 0 is of operation {undeclared}" in said
    assert "nothing has declared which of its parameters name places" in said


async def test_a_retired_operation_meets_the_composing_refusal_and_not_a_place_one() -> None:
    """Its place use can no longer be declared, so the refusal that names
    the retirement is the one a caller can act on."""
    deps = _kernel()
    undeclared = await _an_operation(
        deps, "move", ("path", "from", "to"), drives_devices=False, place_use=None
    )
    pursuit_id = await _a_pursuit(deps, places=("19-bm", "alcf"))
    await _a_round_proposing(
        deps, pursuit_id, [(undeclared, {"path": "scans/", "from": "19-bm", "to": "alcf"})]
    )
    await bind_retire(deps)(
        RetireOperation(operation_id=undeclared), principal_id=uuid4(), correlation_id=uuid4()
    )

    with pytest.raises(OperationCannotBeCitedError):
        await _close(deps, pursuit_id)
