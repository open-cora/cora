"""The definition handler, against in-process stores.

The decider is tested on its own. What is left for the handler is what a
decider never sees: which beamline it asks the gate about, that it refuses
an operation that does not exist before anything is minted, and that the
key it asks the lookup about is the one a row stores, so a second
definition under it is caught.

The lookup here is the in-memory one, which folds the streams and so sees
a definition the moment it lands. The window a deployment's projection
leaves open is driven against Postgres instead, beside the other tests of
this slice that need a real table.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.adapters import InMemorySetupSummaryLookup
from keeper.execution.aggregates.operation import (
    OperationCannotBeCitedError,
    OperationNotFoundError,
)
from keeper.execution.aggregates.setup import (
    SETUP_STREAM_TYPE,
    InvalidSetupNameError,
    OperationCannotTakeSetupError,
    Setup,
    SetupAlreadyExistsError,
    SetupBeamline,
    SetupName,
    load_setup,
)
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_setup import DefineSetup, bind
from keeper.execution.features.retire_operation import RetireOperation
from keeper.execution.features.retire_operation import bind as bind_retire_operation
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import Allow, AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "config": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
        "override": {"type": "object"},
    },
}

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"rotation-axis": {"type": "number"}},
}


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _CountingIdGenerator:
    """Hands out ids and remembers them, so a test can assert none was minted."""

    def __init__(self) -> None:
        self.issued: list[UUID] = []

    def new_id(self) -> UUID:
        minted = uuid4()
        self.issued.append(minted)
        return minted


class _OneBeamlineAuthorize:
    """Allows a call naming this beamline and refuses every other, remembering each."""

    def __init__(self, beamline: str) -> None:
        self._beamline = beamline
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
        if beamline == self._beamline:
            return Allow()
        return Deny(reason=f"not granted at {beamline}")


def _kernel(
    *, authz: object | None = None, event_store: InMemoryEventStore | None = None
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(environment="test"),
        clock=_FixedClock(),
        id_generator=_CountingIdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


def _store(deps: Kernel) -> InMemoryEventStore:
    assert isinstance(deps.event_store, InMemoryEventStore)
    return deps.event_store


def _minted(deps: Kernel) -> list[UUID]:
    generator = deps.id_generator
    assert isinstance(generator, _CountingIdGenerator)
    return generator.issued


async def _an_operation(deps: Kernel, schema: dict[str, Any] | None = None) -> UUID:
    return await bind_define_operation(deps)(
        DefineOperation(name="process", parameters_schema=schema or dict(_PROCESS_SCHEMA)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _define(deps: Kernel, operation_id: UUID, **overrides: Any) -> UUID:
    fields: dict[str, Any] = {
        "beamline": "2-bm",
        "operation_id": operation_id,
        "name": "tomo-default",
        "settings": {"rotation-axis": 1630.0},
        "settings_schema": dict(_SETTINGS_SCHEMA),
    }
    fields.update(overrides)
    return await bind(deps, InMemorySetupSummaryLookup(_store(deps)))(
        DefineSetup(**fields), principal_id=uuid4(), correlation_id=uuid4()
    )


async def test_defining_returns_the_id_the_setup_can_be_loaded_by() -> None:
    deps = _kernel()
    operation_id = await _an_operation(deps)

    setup_id = await _define(deps, operation_id)

    assert await load_setup(deps.event_store, setup_id) == Setup(
        id=setup_id,
        beamline=SetupBeamline("2-bm"),
        operation_id=operation_id,
        name=SetupName("tomo-default"),
        settings={"rotation-axis": 1630.0},
        settings_schema=_SETTINGS_SCHEMA,
        revision=1,
    )


async def test_the_gate_is_asked_at_the_beamline_the_command_names() -> None:
    """The architecture rule proves the handler passes a beamline at all.
    This proves it is the command's own."""
    store = InMemoryEventStore()
    operation_id = await _an_operation(_kernel(event_store=store))
    authz = _OneBeamlineAuthorize("19-bm")

    await _define(_kernel(authz=authz, event_store=store), operation_id, beamline="19-bm")

    assert authz.asked == [("DefineSetup", "19-bm")]


async def test_a_caller_granted_another_beamline_writes_nothing_and_mints_nothing() -> None:
    store = InMemoryEventStore()
    operation_id = await _an_operation(_kernel(event_store=store))
    deps = _kernel(authz=_OneBeamlineAuthorize("19-bm"), event_store=store)

    with pytest.raises(UnauthorizedError, match="not granted at 2-bm"):
        await _define(deps, operation_id, beamline="2-bm")

    assert _minted(deps) == []
    assert store.stream_ids(SETUP_STREAM_TYPE) == []


async def test_a_setup_for_an_operation_nobody_defined_is_refused_before_an_id_is_minted() -> None:
    deps = _kernel()

    with pytest.raises(OperationNotFoundError):
        await _define(deps, uuid4())

    assert _minted(deps) == []


async def test_a_setup_for_a_retired_operation_is_refused_and_leaves_no_stream() -> None:
    deps = _kernel()
    operation_id = await _an_operation(deps)
    await bind_retire_operation(deps)(
        RetireOperation(operation_id=operation_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    with pytest.raises(OperationCannotBeCitedError):
        await _define(deps, operation_id)

    assert _store(deps).stream_ids(SETUP_STREAM_TYPE) == []


async def test_a_setup_for_an_operation_that_takes_none_is_refused() -> None:
    deps = _kernel()
    operation_id = await _an_operation(
        deps, {"$schema": "https://json-schema.org/draft/2020-12/schema"}
    )

    with pytest.raises(OperationCannotTakeSetupError):
        await _define(deps, operation_id)

    assert _store(deps).stream_ids(SETUP_STREAM_TYPE) == []


async def test_a_second_definition_under_a_held_key_is_refused_and_names_the_first() -> None:
    deps = _kernel()
    operation_id = await _an_operation(deps)
    first = await _define(deps, operation_id)

    with pytest.raises(SetupAlreadyExistsError, match=str(first)):
        await _define(deps, operation_id, settings={"rotation-axis": 1700.0})

    assert _store(deps).stream_ids(SETUP_STREAM_TYPE) == [first]


async def test_the_key_is_asked_in_the_form_a_row_stores_it() -> None:
    """The beamline is trimmed on the way into the record, so a second
    definition spelling it with spaces names the same key. A handler that
    asked the lookup with the command's raw string would find nothing and
    let the duplicate through."""
    deps = _kernel()
    operation_id = await _an_operation(deps)
    await _define(deps, operation_id, beamline="2-bm")

    with pytest.raises(SetupAlreadyExistsError):
        await _define(deps, operation_id, beamline="  2-bm  ")


async def test_one_name_under_another_operation_or_beamline_is_another_setup() -> None:
    deps = _kernel()
    operation_id = await _an_operation(deps)
    other_operation = await _an_operation(deps)

    first = await _define(deps, operation_id)
    elsewhere = await _define(deps, operation_id, beamline="19-bm")
    for_another = await _define(deps, other_operation)

    assert len({first, elsewhere, for_another}) == 3


async def test_a_name_no_step_could_carry_is_refused_before_an_id_is_minted() -> None:
    """The lookup is asked with the value objects, so a malformed name is
    refused before the key is asked about and before anything is minted,
    with the error the decider would have raised."""
    deps = _kernel()
    operation_id = await _an_operation(deps)
    minted_before = len(_minted(deps))

    with pytest.raises(InvalidSetupNameError):
        await _define(deps, operation_id, name="Tomo Default")

    assert len(_minted(deps)) == minted_before
