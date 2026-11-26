"""The listing handler and its query, against in-process stores.

The port is tested on its own, against both adapters. What is left here is
what the handler and the query add: that a filter a surface sends as a
string becomes the value object the definition uses, that the page size is
clamped, and that a refused caller reads nothing.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.adapters import InMemorySetupSummaryLookup
from keeper.execution.aggregates.setup import (
    InvalidSetupBeamlineError,
    InvalidSetupNameError,
    SetupBeamline,
    SetupName,
    SetupSummaryPage,
)
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_setup import DefineSetup
from keeper.execution.features.define_setup import bind as bind_define_setup
from keeper.execution.features.list_setups import MAX_PAGE_SIZE, ListSetups, bind
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


class _RecordingLookup:
    """Remembers the limit it was asked for and answers with an empty page."""

    def __init__(self) -> None:
        self.limits: list[int] = []

    async def list_setups(
        self,
        *,
        beamline: SetupBeamline | None,
        operation_id: UUID | None,
        name: SetupName | None,
        limit: int,
        cursor: str | None,
    ) -> SetupSummaryPage:
        _ = (beamline, operation_id, name, cursor)
        self.limits.append(limit)
        return SetupSummaryPage(items=[], next_cursor=None)

    async def find_setup(
        self, *, beamline: SetupBeamline, operation_id: UUID, name: SetupName
    ) -> None:
        _ = (beamline, operation_id, name)


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(environment="test"),
        clock=_FixedClock(),
        id_generator=_Ids(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


def _lookup(deps: Kernel) -> InMemorySetupSummaryLookup:
    assert isinstance(deps.event_store, InMemoryEventStore)
    return InMemorySetupSummaryLookup(deps.event_store)


async def _a_setup(deps: Kernel, operation_id: UUID, *, beamline: str, name: str) -> UUID:
    return await bind_define_setup(deps, _lookup(deps))(
        DefineSetup(
            beamline=beamline,
            operation_id=operation_id,
            name=name,
            settings={"rotation-axis": 1630.0},
            settings_schema=dict(_SETTINGS_SCHEMA),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_listing_by_a_beamline_written_with_spaces_finds_that_beamlines_setups() -> None:
    """The filter goes through the value object the definition uses, so it
    is trimmed the same way and names the same beamline."""
    deps = _kernel()
    operation_id = await bind_define_operation(deps)(
        DefineOperation(name="process", parameters_schema=dict(_PROCESS_SCHEMA)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    wanted = await _a_setup(deps, operation_id, beamline="2-bm", name="tomo-default")
    await _a_setup(deps, operation_id, beamline="19-bm", name="tomo-default")

    page = await bind(deps, _lookup(deps))(
        ListSetups.from_filters(beamline="  2-bm  "),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert [summary.setup_id for summary in page.items] == [wanted]


def test_a_name_filter_no_setup_could_hold_is_refused_rather_than_matching_nothing() -> None:
    with pytest.raises(InvalidSetupNameError):
        ListSetups.from_filters(beamline=None, name="Tomo Default")


def test_a_blank_beamline_filter_is_refused() -> None:
    with pytest.raises(InvalidSetupBeamlineError):
        ListSetups.from_filters(beamline="   ")


async def test_a_page_larger_than_the_bound_is_clamped_before_the_lookup_is_asked() -> None:
    lookup = _RecordingLookup()

    await bind(_kernel(), lookup)(
        ListSetups(limit=MAX_PAGE_SIZE * 10), principal_id=uuid4(), correlation_id=uuid4()
    )

    assert lookup.limits == [MAX_PAGE_SIZE]


async def test_a_denied_caller_cannot_list_setups() -> None:
    lookup = _RecordingLookup()

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind(_kernel(authz=_DenyAllAuthorize()), lookup)(
            ListSetups(), principal_id=uuid4(), correlation_id=uuid4()
        )

    assert lookup.limits == []
