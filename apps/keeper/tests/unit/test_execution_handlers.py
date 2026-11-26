"""The three execution handlers, against in-process stores.

The deciders are tested next door against states built by hand. What is
left here is what only a handler can get wrong: reading the version it
appends at, authorizing under its own command name, and writing to the
stream the command named rather than some other one.

The genuinely concurrent case is not here. Two drivers reporting one
execution at the same instant both fold the same state and both append at the
same version, and only the store's unique constraint decides between
them. That cannot be staged against an in-memory store that serialises
with a lock, so it lives in the integration tier.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.execution import (
    EXECUTION_STREAM_TYPE,
    ExecutionAlreadyEndedError,
    ExecutionCannotBeClaimedError,
    ExecutionStatus,
    PinnedSetup,
    StepOutcome,
    load_execution,
)
from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    ComposedStep,
    ProcedureDefined,
    ProcedureNotFoundError,
    RunStep,
    SetStep,
)
from keeper.execution.aggregates.procedure import to_payload as procedure_payload
from keeper.execution.aggregates.setup import SetupCannotBePinnedError
from keeper.execution.features.claim_execution import ClaimExecution
from keeper.execution.features.claim_execution import bind as bind_claim
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.define_procedure import bind as bind_define_procedure
from keeper.execution.features.define_setup import DefineSetup
from keeper.execution.features.define_setup import bind as bind_define_setup
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.execution.features.dispatch_execution import bind as bind_dispatch
from keeper.execution.features.end_execution import EndExecution
from keeper.execution.features.end_execution import bind as bind_end
from keeper.execution.features.report_step import ReportExecutionStep
from keeper.execution.features.report_step import bind as bind_step
from keeper.execution.features.revise_setup import ReviseSetup
from keeper.execution.features.revise_setup import bind as bind_revise_setup
from keeper.execution.resolving import setup_summary_lookup
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
_STEPS = ("set 2bmb:m1 to 0.0", "run tomo_scan", "set 2bmb:m2 to 5.0")


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _Ids:
    def new_id(self) -> UUID:
        return uuid4()


class _DenyAllAuthorize:
    """Refuses everything, and remembers what it was asked about."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
        beamline: str | None = None,
    ) -> AuthzResult:
        _ = (principal_id, surface_id)
        self.asked.append(command_name)
        return Deny(reason="not on the list")


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(environment="test"),
        clock=_FixedClock(),
        id_generator=_Ids(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _a_procedure(deps: Kernel) -> UUID:
    """A three-move routine, matching the step descriptions above."""
    return await bind_define_procedure(deps)(
        DefineProcedure(
            name="align_then_scan",
            beamline="2-bm",
            steps=(
                SetStep(record="2bmb:m1", to=0.0),
                SetStep(record="2bmb:m2", to=5.0),
                SetStep(record="2bmb:m3", to=1.0),
            ),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_walk(deps: Kernel) -> UUID:
    """One dispatched execution over that routine. Returns its id."""
    procedure_id = await _a_procedure(deps)
    return await bind_dispatch(deps)(
        DispatchExecution(procedure_id=procedure_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_dispatching_a_walk_copies_the_procedures_whole_step_list() -> None:
    deps = _kernel()

    execution_id = await _a_walk(deps)

    execution = await load_execution(deps.event_store, execution_id)
    assert execution is not None
    assert [step.describes for step in execution.steps] == [
        "set 2bmb:m1 to 0.0",
        "set 2bmb:m2 to 5.0",
        "set 2bmb:m3 to 1.0",
    ]
    assert execution.status is ExecutionStatus.DISPATCHED


async def test_dispatching_a_walk_for_a_procedure_that_does_not_exist_is_refused() -> None:
    deps = _kernel()

    with pytest.raises(ProcedureNotFoundError):
        await bind_dispatch(deps)(
            DispatchExecution(procedure_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_two_drivers_claiming_one_dispatch_produce_one_claim_and_one_refusal() -> None:
    """The race the status exists to make visible."""
    deps = _kernel()
    execution_id = await _a_walk(deps)
    claim = bind_claim(deps)

    await claim(
        ClaimExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    with pytest.raises(ExecutionCannotBeClaimedError):
        await claim(
            ClaimExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    execution = await load_execution(deps.event_store, execution_id)
    assert execution is not None
    assert execution.status is ExecutionStatus.CLAIMED


async def test_reporting_steps_one_at_a_time_lands_each_on_the_walks_stream() -> None:
    deps = _kernel()
    execution_id = await _a_walk(deps)

    await bind_step(deps)(
        ReportExecutionStep(execution_id=execution_id, index=0, outcome=StepOutcome.DONE),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    await bind_step(deps)(
        ReportExecutionStep(
            execution_id=execution_id,
            index=1,
            outcome=StepOutcome.BROKEN,
            cause="TimeoutError",
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, version = await deps.event_store.load(EXECUTION_STREAM_TYPE, execution_id)
    assert [row.event_type for row in stored] == [
        "ExecutionDispatched",
        "ExecutionStepDone",
        "ExecutionStepBroken",
    ]
    assert version == 3


async def test_a_walk_ends_with_a_step_still_unreported() -> None:
    """The record a driver that died leaves behind, closed by something else."""
    deps = _kernel()
    execution_id = await _a_walk(deps)
    await bind_step(deps)(
        ReportExecutionStep(execution_id=execution_id, index=0, outcome=StepOutcome.DONE),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    await bind_end(deps)(
        EndExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    execution = await load_execution(deps.event_store, execution_id)
    assert execution is not None
    assert execution.ended
    assert (execution.reported_count, execution.step_count) == (1, 3)


async def test_a_step_reported_after_the_ending_is_refused() -> None:
    deps = _kernel()
    execution_id = await _a_walk(deps)
    await bind_end(deps)(
        EndExecution(execution_id=execution_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    with pytest.raises(ExecutionAlreadyEndedError):
        await bind_step(deps)(
            ReportExecutionStep(execution_id=execution_id, index=0, outcome=StepOutcome.DONE),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_two_walks_in_one_store_do_not_share_a_stream() -> None:
    """A step names its execution, and writing to the wrong one would still fold."""
    deps = _kernel()
    first = await _a_walk(deps)
    second = await _a_walk(deps)

    await bind_step(deps)(
        ReportExecutionStep(execution_id=second, index=2, outcome=StepOutcome.SKIPPED),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    untouched = await load_execution(deps.event_store, first)
    moved = await load_execution(deps.event_store, second)
    assert untouched is not None
    assert moved is not None
    assert untouched.reported_count == 0
    assert moved.steps[2].outcome is StepOutcome.SKIPPED


async def test_the_claimed_timestamp_is_kept_over_the_clock() -> None:
    """A driver at a beamline picks work up on its own clock, and a claim
    relayed late still happened when the driver says it did."""
    deps = _kernel()
    earlier = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
    execution_id = await _a_walk(deps)

    await bind_claim(deps)(
        ClaimExecution(execution_id=execution_id, occurred_at=earlier),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    stored, _version = await deps.event_store.load(EXECUTION_STREAM_TYPE, execution_id)
    assert stored[-1].occurred_at == earlier


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        ("dispatch_execution", "DispatchExecution"),
        ("claim_execution", "ClaimExecution"),
        ("report_step", "ReportExecutionStep"),
        ("end_execution", "EndExecution"),
    ],
)
async def test_each_handler_authorizes_under_its_own_command_name(call: str, expected: str) -> None:
    """A handler wired to a sibling's label would grant the wrong permission."""
    authz = _DenyAllAuthorize()
    deps = _kernel(authz=authz)
    execution_id = uuid4()

    with pytest.raises(UnauthorizedError):
        match call:
            case "dispatch_execution":
                await bind_dispatch(deps)(
                    DispatchExecution(procedure_id=uuid4()),
                    principal_id=uuid4(),
                    correlation_id=uuid4(),
                )
            case "claim_execution":
                await bind_claim(deps)(
                    ClaimExecution(execution_id=execution_id),
                    principal_id=uuid4(),
                    correlation_id=uuid4(),
                )
            case "report_step":
                await bind_step(deps)(
                    ReportExecutionStep(
                        execution_id=execution_id, index=0, outcome=StepOutcome.DONE
                    ),
                    principal_id=uuid4(),
                    correlation_id=uuid4(),
                )
            case _:
                await bind_end(deps)(
                    EndExecution(execution_id=execution_id),
                    principal_id=uuid4(),
                    correlation_id=uuid4(),
                )

    assert authz.asked == [expected]


async def test_a_denied_walk_report_writes_nothing() -> None:
    authz = _DenyAllAuthorize()
    deps = _kernel(authz=authz)

    with pytest.raises(UnauthorizedError):
        await _a_walk(deps)

    assert await deps.event_store.load(EXECUTION_STREAM_TYPE, uuid4()) == ([], 0)


_PROCESS_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"config": {"type": "string"}, "override": {"type": "object"}},
}


def _settings_schema(*described: str) -> dict[str, object]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {name: {"type": "number"} for name in described},
    }


async def _a_process(deps: Kernel) -> UUID:
    return await bind_define_operation(deps)(
        DefineOperation(name="process", parameters_schema=_PROCESS_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_setup(deps: Kernel, operation_id: UUID) -> UUID:
    return await bind_define_setup(deps, setup_summary_lookup(deps))(
        DefineSetup(
            beamline="2-bm",
            operation_id=operation_id,
            name="tomo-default",
            settings={"rotation-axis": 1630.0, "binning": 2},
            settings_schema=_settings_schema("rotation-axis", "binning"),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _revise(deps: Kernel, setup_id: UUID, expected: int, *described: str) -> None:
    await bind_revise_setup(deps)(
        ReviseSetup(
            setup_id=setup_id,
            expected_revision=expected,
            settings=dict.fromkeys(described, 1.0),
            settings_schema=_settings_schema(*described),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


def _processing(operation_id: UUID) -> RunStep:
    return RunStep(
        operation_id=operation_id,
        parameters={"config": "tomo-default", "override": {"binning": 4}},
        scopes=(),
        drives_no_device=True,
    )


async def _a_processing_procedure(deps: Kernel, operation_id: UUID) -> UUID:
    return await bind_define_procedure(deps)(
        DefineProcedure(
            name="reconstruct",
            beamline="2-bm",
            steps=(SetStep(record="2bmb:m1", to=0.0), _processing(operation_id)),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _dispatch(deps: Kernel, procedure_id: UUID) -> UUID:
    return await bind_dispatch(deps)(
        DispatchExecution(procedure_id=procedure_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_procedure_from_before_the_check(deps: Kernel, operation_id: UUID) -> UUID:
    """A procedure written to the log the way one defined before setups were
    checked is there: its run names a setup that nothing holds yet."""
    procedure_id = uuid4()
    defined = ProcedureDefined(
        procedure_id=procedure_id,
        procedure_name="reconstruct",
        beamline="2-bm",
        steps=(ComposedStep(id=uuid4(), step=_processing(operation_id)),),
        occurred_at=_WHEN,
    )
    await deps.event_store.append(
        PROCEDURE_STREAM_TYPE,
        procedure_id,
        0,
        [
            to_new_event(
                event_type="ProcedureDefined",
                payload=procedure_payload(defined),
                occurred_at=_WHEN,
                event_id=uuid4(),
                command_name="DefineProcedure",
                correlation_id=uuid4(),
                principal_id=uuid4(),
            )
        ],
    )
    return procedure_id


async def test_a_dispatch_pins_each_setup_taking_step_to_the_latest_revision() -> None:
    """Revised after the procedure was defined, so the pin can only be right
    if the setup was resolved again at dispatch."""
    deps = _kernel()
    operation_id = await _a_process(deps)
    setup_id = await _a_setup(deps, operation_id)
    procedure_id = await _a_processing_procedure(deps, operation_id)
    await _revise(deps, setup_id, 1, "rotation-axis", "binning")

    execution = await load_execution(deps.event_store, await _dispatch(deps, procedure_id))

    assert execution is not None
    assert [step.setup for step in execution.steps] == [
        None,
        PinnedSetup(setup_id=setup_id, revision=2),
    ]


async def test_the_pin_lands_in_the_append_that_writes_the_genesis() -> None:
    """One append, one correlation: there is no moment at which the execution
    exists and its setups have not been settled."""
    deps = _kernel()
    operation_id = await _a_process(deps)
    await _a_setup(deps, operation_id)
    procedure_id = await _a_processing_procedure(deps, operation_id)

    execution_id = await _dispatch(deps, procedure_id)

    rows, version = await deps.event_store.load(EXECUTION_STREAM_TYPE, execution_id)
    assert [row.event_type for row in rows] == ["ExecutionDispatched", "ExecutionSetupsPinned"]
    assert version == 2
    assert len({row.correlation_id for row in rows}) == 1


async def test_a_dispatch_whose_setup_was_revised_out_from_under_its_override_is_refused() -> None:
    deps = _kernel()
    operation_id = await _a_process(deps)
    setup_id = await _a_setup(deps, operation_id)
    procedure_id = await _a_processing_procedure(deps, operation_id)
    await _revise(deps, setup_id, 1, "rotation-axis")

    with pytest.raises(SetupCannotBePinnedError, match="binning"):
        await _dispatch(deps, procedure_id)

    assert isinstance(deps.event_store, InMemoryEventStore)
    assert list(deps.event_store.stream_ids(EXECUTION_STREAM_TYPE)) == []


async def test_a_procedure_from_before_its_setup_existed_dispatches_once_one_holds_the_name() -> (
    None
):
    """Resolved by name at dispatch, so the refusal lasts exactly as long as
    nothing holds the name, and defining the setup is the whole fix."""
    deps = _kernel()
    operation_id = await _a_process(deps)
    procedure_id = await _a_procedure_from_before_the_check(deps, operation_id)

    with pytest.raises(SetupCannotBePinnedError, match="tomo-default"):
        await _dispatch(deps, procedure_id)
    setup_id = await _a_setup(deps, operation_id)
    execution = await load_execution(deps.event_store, await _dispatch(deps, procedure_id))

    assert execution is not None
    assert execution.steps[0].setup == PinnedSetup(setup_id=setup_id, revision=1)
