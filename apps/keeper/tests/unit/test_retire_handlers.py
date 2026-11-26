"""The two retirement handlers, and what a retirement then stops.

The deciders are tested on their own. What is left for a handler is the
part a decider never sees: which moment it stamps, which version it
appends at, which question it puts to the authorization port, and in
what order it does those things.

The second half drives the slices a retirement is meant to stop, through
their own handlers, because a refusal that holds in a decider holds only
if the handler hands it the folded status. A handler that built its
context from anything else would leave every decider test green.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.proposal import ProposalStatus, load_proposal
from keeper.counsel.features.adopt_proposal import AdoptProposal
from keeper.counsel.features.adopt_proposal import bind as bind_adopt
from keeper.counsel.features.make_proposal import MakeProposal
from keeper.counsel.features.make_proposal import bind as bind_propose
from keeper.execution.aggregates.execution import EXECUTION_STREAM_TYPE
from keeper.execution.aggregates.operation import (
    OPERATION_STREAM_TYPE,
    OperationCannotBeCitedError,
    OperationCannotBeRetiredError,
    OperationNotFoundError,
    OperationRetired,
    OperationStatus,
    load_operation,
)
from keeper.execution.aggregates.operation import to_payload as operation_payload
from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    ProcedureCannotBeDispatchedError,
    ProcedureCannotBeRetiredError,
    ProcedureNotFoundError,
    ProcedureStatus,
    RunStep,
    SetStep,
    load_procedure,
)
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_procedure import DefineProcedure
from keeper.execution.features.define_procedure import bind as bind_define_procedure
from keeper.execution.features.dispatch_execution import DispatchExecution
from keeper.execution.features.dispatch_execution import bind as bind_dispatch
from keeper.execution.features.retire_operation import RetireOperation
from keeper.execution.features.retire_operation import bind as bind_retire_operation
from keeper.execution.features.retire_procedure import RetireProcedure
from keeper.execution.features.retire_procedure import bind as bind_retire_procedure
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import Allow, AllowAllAuthorize, ConcurrencyError, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.settings import Settings
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

pytestmark = pytest.mark.unit

_CLOCK_NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}


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


class _OneBeamlineAuthorize:
    """Allows a call naming this beamline, and refuses every other.

    Stands in for a policy that grants a station its own procedures and
    nobody else's, which is what a fence by beamline is for.
    """

    def __init__(self, beamline: str) -> None:
        self._beamline = beamline

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
        beamline: str | None = None,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        if beamline == self._beamline:
            return Allow()
        return Deny(reason=f"not granted at {beamline}")


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
        beamline: str | None = None,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id, beamline)
        return Deny(reason="not granted in this test")


class _RacingEventStore(InMemoryEventStore):
    """Lands a competing retirement the first time a live stream is read.

    Stands in for a second caller retiring the same record a moment
    earlier: the handler folds a state that is stale by the time it
    writes.
    """

    def __init__(self) -> None:
        super().__init__()
        self.raced = False

    async def load(self, stream_type: str, stream_id: UUID) -> tuple[list[StoredEvent], int]:
        rows, version = await super().load(stream_type, stream_id)
        if not self.raced and version > 0 and stream_type == OPERATION_STREAM_TYPE:
            self.raced = True
            event = OperationRetired(operation_id=stream_id, occurred_at=_CLOCK_NOW)
            await super().append(
                stream_type,
                stream_id,
                version,
                [
                    to_new_event(
                        event_type=type(event).__name__,
                        payload=operation_payload(event),
                        occurred_at=_CLOCK_NOW,
                        event_id=uuid4(),
                        command_name="RetireOperation",
                        correlation_id=uuid4(),
                        principal_id=uuid4(),
                    )
                ],
            )
        return rows, version


def _kernel(
    *, authz: object | None = None, event_store: InMemoryEventStore | None = None
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(environment="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4IdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


def _store(deps: Kernel) -> InMemoryEventStore:
    assert isinstance(deps.event_store, InMemoryEventStore)
    return deps.event_store


async def _an_operation(deps: Kernel) -> UUID:
    return await bind_define_operation(deps)(
        DefineOperation(name="transfer", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _a_procedure(deps: Kernel, *, runs: UUID | None = None) -> UUID:
    steps = (
        (RunStep(operation_id=runs, drives_no_device=True),)
        if runs is not None
        else (SetStep(record="19bm:m1", to=0.0),)
    )
    return await bind_define_procedure(deps)(
        DefineProcedure(name="Move a dataset", beamline="19-bm", steps=steps),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _retire_operation(deps: Kernel, operation_id: UUID) -> None:
    await bind_retire_operation(deps)(
        RetireOperation(operation_id=operation_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _retire_procedure(deps: Kernel, procedure_id: UUID) -> None:
    await bind_retire_procedure(deps)(
        RetireProcedure(procedure_id=procedure_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_retiring_an_operation_appends_one_event_stamped_by_the_clock() -> None:
    """Retiring is an act performed here, so the moment this system writes
    the record is the moment it happened, and the command offers no other."""
    deps = _kernel()
    operation_id = await _an_operation(deps)

    await _retire_operation(deps, operation_id)

    stored, version = await deps.event_store.load(OPERATION_STREAM_TYPE, operation_id)
    assert [row.event_type for row in stored] == ["OperationDefined", "OperationRetired"]
    assert stored[1].occurred_at == _CLOCK_NOW
    assert version == 2
    operation = await load_operation(deps.event_store, operation_id)
    assert operation is not None
    assert operation.status is OperationStatus.RETIRED


async def test_retiring_an_operation_twice_is_refused_and_appends_nothing() -> None:
    deps = _kernel()
    operation_id = await _an_operation(deps)
    await _retire_operation(deps, operation_id)

    with pytest.raises(OperationCannotBeRetiredError):
        await _retire_operation(deps, operation_id)

    _rows, version = await deps.event_store.load(OPERATION_STREAM_TYPE, operation_id)
    assert version == 2


async def test_retiring_an_operation_nobody_defined_is_refused() -> None:
    deps = _kernel()

    with pytest.raises(OperationNotFoundError):
        await _retire_operation(deps, uuid4())


async def test_retiring_an_operation_asks_the_gate_without_a_beamline() -> None:
    """An operation is one value for the whole facility, so there is no
    station to name, and a permission for one would never match."""
    authz = _RecordingAuthorize()
    deps = _kernel(authz=authz)
    operation_id = await _an_operation(deps)

    await _retire_operation(deps, operation_id)

    assert authz.asked[-1] == ("RetireOperation", None)


async def test_a_caller_refused_an_operation_retirement_writes_nothing() -> None:
    store = InMemoryEventStore()
    operation_id = await _an_operation(_kernel(event_store=store))
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)

    with pytest.raises(UnauthorizedError):
        await _retire_operation(deps, operation_id)

    _rows, version = await store.load(OPERATION_STREAM_TYPE, operation_id)
    assert version == 1


async def test_a_retirement_landing_between_the_read_and_the_append_is_refused() -> None:
    """A handler holding a stale fold must lose the append, not win it,
    so two callers retiring one operation leave one row and one conflict."""
    store = _RacingEventStore()
    operation_id = await _an_operation(_kernel(event_store=store))
    deps = _kernel(event_store=store)

    with pytest.raises(ConcurrencyError):
        await _retire_operation(deps, operation_id)

    assert store.raced, "the racing store never injected a competing write"
    _rows, version = await store.load(OPERATION_STREAM_TYPE, operation_id)
    assert version == 2, "only the competing retirement should have landed"


async def test_retiring_a_procedure_appends_one_event_stamped_by_the_clock() -> None:
    deps = _kernel()
    procedure_id = await _a_procedure(deps)

    await _retire_procedure(deps, procedure_id)

    stored, version = await deps.event_store.load(PROCEDURE_STREAM_TYPE, procedure_id)
    assert [row.event_type for row in stored] == ["ProcedureDefined", "ProcedureRetired"]
    assert stored[1].occurred_at == _CLOCK_NOW
    assert version == 2
    procedure = await load_procedure(deps.event_store, procedure_id)
    assert procedure is not None
    assert procedure.status is ProcedureStatus.RETIRED


async def test_retiring_a_procedure_twice_is_refused_and_appends_nothing() -> None:
    deps = _kernel()
    procedure_id = await _a_procedure(deps)
    await _retire_procedure(deps, procedure_id)

    with pytest.raises(ProcedureCannotBeRetiredError):
        await _retire_procedure(deps, procedure_id)

    _rows, version = await deps.event_store.load(PROCEDURE_STREAM_TYPE, procedure_id)
    assert version == 2


async def test_retiring_a_procedure_asks_the_gate_at_the_procedures_own_beamline() -> None:
    """The architecture rule proves the handler passes a beamline at all.
    This proves it is the one the procedure was composed for."""
    authz = _RecordingAuthorize()
    deps = _kernel(authz=authz)
    procedure_id = await _a_procedure(deps)

    await _retire_procedure(deps, procedure_id)

    assert authz.asked[-1] == ("RetireProcedure", "19-bm")


async def test_a_caller_granted_another_beamline_cannot_retire_this_ones_procedure() -> None:
    store = InMemoryEventStore()
    procedure_id = await _a_procedure(_kernel(event_store=store))
    deps = _kernel(authz=_OneBeamlineAuthorize("2-bm"), event_store=store)

    with pytest.raises(UnauthorizedError, match="not granted at 19-bm"):
        await _retire_procedure(deps, procedure_id)

    _rows, version = await store.load(PROCEDURE_STREAM_TYPE, procedure_id)
    assert version == 1


async def test_a_caller_granted_the_procedures_beamline_may_retire_it() -> None:
    store = InMemoryEventStore()
    procedure_id = await _a_procedure(_kernel(event_store=store))
    deps = _kernel(authz=_OneBeamlineAuthorize("19-bm"), event_store=store)

    await _retire_procedure(deps, procedure_id)

    _rows, version = await store.load(PROCEDURE_STREAM_TYPE, procedure_id)
    assert version == 2


async def test_a_procedure_id_naming_nothing_is_refused_before_the_gate_is_asked() -> None:
    """There is no beamline to ask about, which is why the read comes first."""
    authz = _RecordingAuthorize()
    deps = _kernel(authz=authz)

    with pytest.raises(ProcedureNotFoundError):
        await _retire_procedure(deps, uuid4())

    assert authz.asked == []


async def test_a_run_citing_a_retired_operation_is_refused_when_composed() -> None:
    deps = _kernel()
    operation_id = await _an_operation(deps)
    await _retire_operation(deps, operation_id)

    with pytest.raises(OperationCannotBeCitedError):
        await _a_procedure(deps, runs=operation_id)

    assert _store(deps).stream_ids(PROCEDURE_STREAM_TYPE) == []


async def test_a_retired_procedure_is_refused_at_dispatch_and_opens_no_execution() -> None:
    deps = _kernel()
    procedure_id = await _a_procedure(deps)
    await _retire_procedure(deps, procedure_id)

    with pytest.raises(ProcedureCannotBeDispatchedError):
        await bind_dispatch(deps)(
            DispatchExecution(procedure_id=procedure_id),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert _store(deps).stream_ids(EXECUTION_STREAM_TYPE) == []


async def test_a_procedure_whose_operation_was_retired_after_it_was_composed_is_refused() -> None:
    """The procedure itself is still active. Retiring the operation alone
    is enough to stop its dispatch, so nobody has to find and retire every
    procedure that cites it first."""
    deps = _kernel()
    operation_id = await _an_operation(deps)
    procedure_id = await _a_procedure(deps, runs=operation_id)
    await _retire_operation(deps, operation_id)

    with pytest.raises(OperationCannotBeCitedError):
        await bind_dispatch(deps)(
            DispatchExecution(procedure_id=procedure_id),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    procedure = await load_procedure(deps.event_store, procedure_id)
    assert procedure is not None
    assert procedure.status is ProcedureStatus.ACTIVE
    assert _store(deps).stream_ids(EXECUTION_STREAM_TYPE) == []


async def test_a_proposal_for_a_retired_operation_is_refused_when_made() -> None:
    deps = _kernel()
    operation_id = await _an_operation(deps)
    await _retire_operation(deps, operation_id)

    with pytest.raises(OperationCannotBeCitedError):
        await bind_propose(deps)(
            MakeProposal(operation_id=operation_id, parameters={}),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_proposal_made_before_its_operation_was_retired_cannot_be_adopted() -> None:
    """Adoption composes and dispatches in one transaction without passing
    through either guarded slice's handler, so this is the path that would
    otherwise dispatch old advice nothing answers to."""
    deps = _kernel()
    operation_id = await _an_operation(deps)
    proposal_id = await bind_propose(deps)(
        MakeProposal(operation_id=operation_id, parameters={}),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    await _retire_operation(deps, operation_id)

    with pytest.raises(OperationCannotBeCitedError):
        await bind_adopt(deps)(
            AdoptProposal(
                proposal_id=proposal_id, beamline="19-bm", scopes=(), drives_no_device=True
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    proposal = await load_proposal(deps.event_store, proposal_id)
    assert proposal is not None
    assert proposal.status is ProposalStatus.OPEN
    assert _store(deps).stream_ids(EXECUTION_STREAM_TYPE) == []
