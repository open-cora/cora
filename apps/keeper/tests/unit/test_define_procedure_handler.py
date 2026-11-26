"""The composition handler, against in-process stores.

Create-style, so there is no load of its own stream to get wrong. What is
interesting here is the reading it does of OTHER streams: a procedure
cites operations, the decider is pure and cannot fetch them, and this is the
first handler in the tree that loads several siblings rather than one.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.operation import OperationNotFoundError
from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    InvalidProcedureParametersError,
    ProcedureName,
    RunStep,
    SetStep,
    load_procedure,
)
from keeper.execution.aggregates.setup import SETUP_STREAM_TYPE
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_procedure import DefineProcedure, bind
from keeper.execution.features.define_setup import DefineSetup
from keeper.execution.features.define_setup import bind as bind_define_setup
from keeper.execution.resolving import setup_summary_lookup
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 24, 11, 0, tzinfo=UTC)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _CountingEventStore(InMemoryEventStore):
    """Counts loads, so a test can assert a repeated operation is read once."""

    def __init__(self) -> None:
        super().__init__()
        self.loads: list[tuple[str, UUID]] = []

    async def load(self, stream_type: str, stream_id: UUID) -> tuple[list[Any], int]:  # pyright: ignore[reportIncompatibleMethodOverride]
        self.loads.append((stream_type, stream_id))
        return await super().load(stream_type, stream_id)


class _IdGenerator:
    def new_id(self) -> UUID:
        return uuid4()


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
        beamline: str | None = None,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not on the list")


def _kernel(
    *,
    authz: object | None = None,
    event_store: InMemoryEventStore | None = None,
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(environment="test"),
        clock=_FixedClock(),
        id_generator=_IdGenerator(),  # pyright: ignore[reportArgumentType]
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


async def _an_operation(deps: Kernel) -> UUID:
    return await bind_define_operation(deps)(
        DefineOperation(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_composing_returns_the_id_the_procedure_can_be_loaded_by() -> None:
    deps = _kernel()
    operation_id = await _an_operation(deps)
    steps = (
        SetStep(record="2bmb:m1", to=12.5),
        RunStep(
            operation_id=operation_id,
            parameters={"exposure_seconds": 0.2},
            scopes=("2bmb:m1", "2bmb:det:"),
        ),
    )

    procedure_id = await bind(deps)(
        DefineProcedure(name="tomography", beamline="2-bm", steps=steps),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    procedure = await load_procedure(deps.event_store, procedure_id)
    assert procedure is not None
    assert procedure.name == ProcedureName("tomography")
    assert tuple(composed.step for composed in procedure.steps) == steps
    assert len({composed.id for composed in procedure.steps}) == len(steps)


async def test_a_procedure_citing_a_plan_that_does_not_exist_is_refused() -> None:
    """The check the decider cannot make, because discovering an absence
    needs the store and a decider has none."""
    deps = _kernel()
    absent = uuid4()

    with pytest.raises(OperationNotFoundError):
        await bind(deps)(
            DefineProcedure(
                name="tomography",
                beamline="2-bm",
                steps=(RunStep(operation_id=absent, parameters={}, scopes=("2bmb:m1",)),),
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_the_same_operation_acquired_many_times_is_read_once() -> None:
    """A tomography procedure runs the same operation at every sample
    position. Reading that stream once per step would make composing a
    routine cost a replay per step for no new information."""
    store = _CountingEventStore()
    deps = _kernel(event_store=store)
    operation_id = await _an_operation(deps)
    store.loads.clear()

    await bind(deps)(
        DefineProcedure(
            name="tomography",
            beamline="2-bm",
            steps=tuple(
                RunStep(
                    operation_id=operation_id,
                    parameters={"exposure_seconds": 0.2},
                    scopes=(f"2bmb:m{i}",),
                )
                for i in range(5)
            ),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert store.loads.count(("Operation", operation_id)) == 1


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    caller = uuid4()

    procedure_id = await bind(deps)(
        DefineProcedure(
            name="tomography", beamline="2-bm", steps=(SetStep(record="2bmb:m1", to=1.0),)
        ),
        principal_id=caller,
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(PROCEDURE_STREAM_TYPE, procedure_id)
    assert rows[0].principal_id == caller


async def test_a_denied_caller_gets_an_error_and_writes_nothing() -> None:
    store = InMemoryEventStore()
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind(deps)(
            DefineProcedure(
                name="tomography", beamline="2-bm", steps=(SetStep(record="2bmb:m1", to=1.0),)
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert list(store.stream_ids(PROCEDURE_STREAM_TYPE)) == []


async def test_a_denied_caller_is_refused_before_any_plan_is_read() -> None:
    """Authorization settles first, so a caller who may not compose
    cannot use this endpoint to learn which operation ids exist."""
    store = _CountingEventStore()
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)

    with pytest.raises(UnauthorizedError):
        await bind(deps)(
            DefineProcedure(
                name="tomography",
                beamline="2-bm",
                steps=(RunStep(operation_id=uuid4(), parameters={}, scopes=("2bmb:m1",)),),
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert store.loads == []


_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"config": {"type": "string"}, "override": {"type": "object"}},
}

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"rotation-axis": {"type": "number"}, "binning": {"type": "integer"}},
}


async def _a_process(deps: Kernel) -> UUID:
    return await bind_define_operation(deps)(
        DefineOperation(name="process", parameters_schema=_PROCESS_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_setup(deps: Kernel, operation_id: UUID, *, beamline: str = "2-bm") -> UUID:
    return await bind_define_setup(deps, setup_summary_lookup(deps))(
        DefineSetup(
            beamline=beamline,
            operation_id=operation_id,
            name="tomo-default",
            settings={"rotation-axis": 1630.0, "binning": 2},
            settings_schema=_SETTINGS_SCHEMA,
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


def _processing(operation_id: UUID, *, count: int = 1, beamline: str = "2-bm") -> DefineProcedure:
    return DefineProcedure(
        name="reconstruct",
        beamline=beamline,
        steps=tuple(
            RunStep(
                operation_id=operation_id,
                parameters={"config": "tomo-default", "override": {"binning": 4}},
                scopes=(),
                drives_no_device=True,
            )
            for _ in range(count)
        ),
    )


async def test_a_run_naming_a_setup_defined_at_the_procedures_beamline_is_defined() -> None:
    deps = _kernel()
    operation_id = await _a_process(deps)
    await _a_setup(deps, operation_id)

    procedure_id = await bind(deps)(
        _processing(operation_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert await load_procedure(deps.event_store, procedure_id) is not None


async def test_a_setup_defined_at_another_beamline_does_not_satisfy_the_run() -> None:
    """Resolved at the procedure's own beamline, so a setup of the same name
    elsewhere is the absence the refusal reports, and nothing is written."""
    store = InMemoryEventStore()
    deps = _kernel(event_store=store)
    operation_id = await _a_process(deps)
    await _a_setup(deps, operation_id, beamline="32-id")

    with pytest.raises(InvalidProcedureParametersError, match="tomo-default"):
        await bind(deps)(_processing(operation_id), principal_id=uuid4(), correlation_id=uuid4())

    assert list(store.stream_ids(PROCEDURE_STREAM_TYPE)) == []


async def test_a_run_naming_a_setup_nobody_defined_is_refused_with_its_index() -> None:
    deps = _kernel()
    operation_id = await _a_process(deps)

    with pytest.raises(InvalidProcedureParametersError) as caught:
        await bind(deps)(
            DefineProcedure(
                name="reconstruct",
                beamline="2-bm",
                steps=(
                    SetStep(record="2bmb:m1", to=1.0),
                    _processing(operation_id).steps[0],
                ),
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert caught.value.index == 1


async def test_the_same_setup_named_by_many_runs_is_read_once() -> None:
    """For the reason a repeated operation is: a name resolves to one setup,
    and replaying its stream once per run would learn nothing new."""
    store = _CountingEventStore()
    deps = _kernel(event_store=store)
    operation_id = await _a_process(deps)
    setup_id = await _a_setup(deps, operation_id)
    reads: list[int] = []
    for count in (1, 4):
        store.loads.clear()
        await bind(deps)(
            _processing(operation_id, count=count), principal_id=uuid4(), correlation_id=uuid4()
        )
        reads.append(store.loads.count((SETUP_STREAM_TYPE, setup_id)))

    one_run, four_runs = reads
    assert one_run > 0
    assert four_runs == one_run


async def test_a_run_whose_operation_takes_no_setup_is_never_looked_up() -> None:
    """Asked of the operation, not the parameters: a config that reads like a
    setup's name on a run of an operation that takes none resolves nothing,
    so a procedure of such runs costs what it cost before setups existed."""
    store = _CountingEventStore()
    deps = _kernel(event_store=store)
    plain = await _an_operation(deps)
    await _a_setup(deps, await _a_process(deps))
    store.loads.clear()

    await bind(deps)(
        DefineProcedure(
            name="tomography",
            beamline="2-bm",
            steps=(
                RunStep(
                    operation_id=plain,
                    parameters={"exposure_seconds": 0.2, "config": "tomo-default"},
                    scopes=("2bmb:det:",),
                ),
            ),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert [stream_type for stream_type, _ in store.loads] == ["Operation"]
