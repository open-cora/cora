"""The read handler, against in-process stores.

A read decides nothing, so what is left to check is which revision comes
back, and the refusals a read can still owe: a caller who was refused, an
id that names nothing, and a revision the setup has not reached, which is
told apart from the id so the caller learns how far the setup goes.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.adapters import InMemorySetupSummaryLookup
from keeper.execution.aggregates.setup import SetupNotFoundError, SetupRevisionNotFoundError
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_setup import DefineSetup
from keeper.execution.features.define_setup import bind as bind_define_setup
from keeper.execution.features.get_setup import GetSetup, bind
from keeper.execution.features.revise_setup import ReviseSetup
from keeper.execution.features.revise_setup import bind as bind_revise_setup
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.deps import make_inmemory_kernel
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.ports import AllowAllAuthorize, Deny
from keeper.infrastructure.ports.authorize import AuthzResult
from keeper.infrastructure.settings import Settings
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"config": {"type": "string"}, "override": {"type": "object"}},
}

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"rotation-axis": {"type": "number"}},
}


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _Ids:
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
        _ = (principal_id, command_name, surface_id, beamline)
        return Deny(reason="not on the list")


def _kernel(
    *, authz: object | None = None, event_store: InMemoryEventStore | None = None
) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(environment="test"),
        clock=_FixedClock(),
        id_generator=_Ids(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=event_store or InMemoryEventStore(),
    )


async def _a_setup_revised_twice(deps: Kernel) -> UUID:
    """A setup at revision 3, its axis 1630.0, then 1631.5, then 1632.0."""
    assert isinstance(deps.event_store, InMemoryEventStore)
    operation_id = await bind_define_operation(deps)(
        DefineOperation(name="process", parameters_schema=dict(_PROCESS_SCHEMA)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    setup_id = await bind_define_setup(deps, InMemorySetupSummaryLookup(deps.event_store))(
        DefineSetup(
            beamline="2-bm",
            operation_id=operation_id,
            name="tomo-default",
            settings={"rotation-axis": 1630.0},
            settings_schema=dict(_SETTINGS_SCHEMA),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    for expected_revision, axis in ((1, 1631.5), (2, 1632.0)):
        await bind_revise_setup(deps)(
            ReviseSetup(
                setup_id=setup_id,
                expected_revision=expected_revision,
                settings={"rotation-axis": axis},
                settings_schema=dict(_SETTINGS_SCHEMA),
            ),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )
    return setup_id


async def _get(deps: Kernel, setup_id: UUID, revision: int | None = None) -> Any:
    return await bind(deps)(
        GetSetup(setup_id=setup_id, revision=revision),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_reading_a_setup_gives_back_its_latest_revision() -> None:
    deps = _kernel()
    setup_id = await _a_setup_revised_twice(deps)

    setup = await _get(deps, setup_id)

    assert (setup.revision, setup.settings) == (3, {"rotation-axis": 1632.0})


@pytest.mark.parametrize(("revision", "axis"), [(1, 1630.0), (2, 1631.5), (3, 1632.0)])
async def test_reading_a_named_revision_gives_back_that_revision_as_it_was_written(
    revision: int, axis: float
) -> None:
    deps = _kernel()
    setup_id = await _a_setup_revised_twice(deps)

    setup = await _get(deps, setup_id, revision)

    assert (setup.revision, setup.settings) == (revision, {"rotation-axis": axis})


async def test_reading_a_setup_that_was_never_defined_is_refused() -> None:
    with pytest.raises(SetupNotFoundError):
        await _get(_kernel(), uuid4())


@pytest.mark.parametrize("revision", [0, 4])
async def test_reading_a_revision_the_setup_has_not_reached_says_how_far_it_goes(
    revision: int,
) -> None:
    deps = _kernel()
    setup_id = await _a_setup_revised_twice(deps)

    with pytest.raises(SetupRevisionNotFoundError, match="run from 1 to 3") as refused:
        await _get(deps, setup_id, revision)

    assert refused.value.latest == 3


async def test_a_denied_caller_cannot_read_a_setup() -> None:
    store = InMemoryEventStore()
    setup_id = await _a_setup_revised_twice(_kernel(event_store=store))

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await _get(_kernel(authz=_DenyAllAuthorize(), event_store=store), setup_id)
