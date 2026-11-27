"""The handler that declares an operation's device use.

The decider is tested on its own. What is left for the handler is what a
decider never sees: which moment it stamps, which version it appends at,
which question it puts to the authorization port, and that a refusal or
a lost race leaves the stream as it was.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.operation import (
    OPERATION_STREAM_TYPE,
    OperationDeviceUseCannotBeDeclaredError,
    OperationDeviceUseDeclared,
    OperationNotFoundError,
    load_operation,
)
from keeper.execution.aggregates.operation import to_payload as operation_payload
from keeper.execution.features.declare_operation_device_use import (
    DeclareOperationDeviceUse,
    bind,
)
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
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

_CLOCK_NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
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
    """Lands a competing declaration the first time a live operation stream is read.

    Stands in for a second caller declaring the same operation a moment
    earlier: the handler folds a state that is stale by the time it writes.
    """

    def __init__(self) -> None:
        super().__init__()
        self.raced = False

    async def load(self, stream_type: str, stream_id: UUID) -> tuple[list[StoredEvent], int]:
        rows, version = await super().load(stream_type, stream_id)
        if not self.raced and version > 0 and stream_type == OPERATION_STREAM_TYPE:
            self.raced = True
            event = OperationDeviceUseDeclared(
                operation_id=stream_id, drives_devices=True, occurred_at=_CLOCK_NOW
            )
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
                        command_name="DeclareOperationDeviceUse",
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


async def _an_operation(deps: Kernel) -> UUID:
    return await bind_define_operation(deps)(
        DefineOperation(name="transfer", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _declare(deps: Kernel, operation_id: UUID, drives_devices: bool) -> None:
    await bind(deps)(
        DeclareOperationDeviceUse(operation_id=operation_id, drives_devices=drives_devices),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_declaring_appends_one_event_stamped_by_the_clock() -> None:
    """Declaring is an act performed here, so the command offers no other moment."""
    deps = _kernel()
    operation_id = await _an_operation(deps)

    await _declare(deps, operation_id, False)

    stored, version = await deps.event_store.load(OPERATION_STREAM_TYPE, operation_id)
    assert [row.event_type for row in stored] == ["OperationDefined", "OperationDeviceUseDeclared"]
    assert stored[1].occurred_at == _CLOCK_NOW
    assert version == 2
    operation = await load_operation(deps.event_store, operation_id)
    assert operation is not None
    assert operation.drives_devices is False


async def test_declaring_a_second_time_is_refused_and_appends_nothing() -> None:
    deps = _kernel()
    operation_id = await _an_operation(deps)
    await _declare(deps, operation_id, True)

    with pytest.raises(OperationDeviceUseCannotBeDeclaredError):
        await _declare(deps, operation_id, True)

    _rows, version = await deps.event_store.load(OPERATION_STREAM_TYPE, operation_id)
    assert version == 2


async def test_declaring_an_operation_nobody_defined_is_refused() -> None:
    deps = _kernel()

    with pytest.raises(OperationNotFoundError):
        await _declare(deps, uuid4(), True)


async def test_declaring_asks_the_gate_without_a_beamline() -> None:
    """An operation is one value for the whole facility, so there is no
    station to name, and a permission naming one would never match."""
    authz = _RecordingAuthorize()
    deps = _kernel(authz=authz)
    operation_id = await _an_operation(deps)

    await _declare(deps, operation_id, True)

    assert authz.asked[-1] == ("DeclareOperationDeviceUse", None)


async def test_a_caller_refused_a_declaration_writes_nothing() -> None:
    store = InMemoryEventStore()
    operation_id = await _an_operation(_kernel(event_store=store))
    deps = _kernel(authz=_DenyAllAuthorize(), event_store=store)

    with pytest.raises(UnauthorizedError):
        await _declare(deps, operation_id, False)

    _rows, version = await store.load(OPERATION_STREAM_TYPE, operation_id)
    assert version == 1


async def test_a_declaration_landing_between_the_read_and_the_append_is_refused() -> None:
    """Two callers declaring one operation leave one declaration and one conflict."""
    store = _RacingEventStore()
    operation_id = await _an_operation(_kernel(event_store=store))
    deps = _kernel(event_store=store)

    with pytest.raises(ConcurrencyError):
        await _declare(deps, operation_id, False)

    assert store.raced, "the racing store never injected a competing write"
    operation = await load_operation(store, operation_id)
    assert operation is not None
    assert operation.drives_devices is True, "only the competing declaration should have landed"
