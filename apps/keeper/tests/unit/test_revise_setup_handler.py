"""The revising handler, against in-process stores.

What a decider never sees: the moment the handler stamps, the version it
appends at, the beamline it asks the gate about and where it got it, and
the number it hands back.

Two windows open between a caller's read and the write, and each has its
guard. A caller whose read went stale before it sent the revision is
refused by the revision number it carries, which is driven with two
callers reading one setup. A revision landing between the handler's own
read and its append is refused by the version it appends at, which is
driven with a store that injects one.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.adapters import InMemorySetupSummaryLookup
from keeper.execution.aggregates.setup import (
    SETUP_STREAM_TYPE,
    SetupCannotBeRevisedError,
    SetupNotFoundError,
    SetupRevised,
    load_setup,
    load_setup_revisions,
)
from keeper.execution.aggregates.setup import to_payload as setup_payload
from keeper.execution.features.define_operation import DefineOperation
from keeper.execution.features.define_operation import bind as bind_define_operation
from keeper.execution.features.define_setup import DefineSetup
from keeper.execution.features.define_setup import bind as bind_define_setup
from keeper.execution.features.revise_setup import ReviseSetup, bind
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
        return _CLOCK_NOW


class _Uuid4IdGenerator:
    def new_id(self) -> UUID:
        return uuid4()


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


class _RacingEventStore(InMemoryEventStore):
    """Lands a competing revision the first time a live setup stream is read.

    Stands in for a second caller revising the same setup a moment earlier:
    the handler folds a state that is stale by the time it writes.
    """

    def __init__(self) -> None:
        super().__init__()
        self.raced = False

    async def load(self, stream_type: str, stream_id: UUID) -> tuple[list[StoredEvent], int]:
        rows, version = await super().load(stream_type, stream_id)
        if not self.raced and version > 0 and stream_type == SETUP_STREAM_TYPE:
            self.raced = True
            event = SetupRevised(
                setup_id=stream_id,
                revision=version + 1,
                settings={"rotation-axis": 9999.0},
                settings_schema=dict(_SETTINGS_SCHEMA),
                occurred_at=_CLOCK_NOW,
            )
            await super().append(
                stream_type,
                stream_id,
                version,
                [
                    to_new_event(
                        event_type=type(event).__name__,
                        payload=setup_payload(event),
                        occurred_at=_CLOCK_NOW,
                        event_id=uuid4(),
                        command_name="ReviseSetup",
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


async def _a_setup(deps: Kernel, *, beamline: str = "19-bm") -> UUID:
    assert isinstance(deps.event_store, InMemoryEventStore)
    operation_id = await bind_define_operation(deps)(
        DefineOperation(name="process", parameters_schema=dict(_PROCESS_SCHEMA)),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await bind_define_setup(deps, InMemorySetupSummaryLookup(deps.event_store))(
        DefineSetup(
            beamline=beamline,
            operation_id=operation_id,
            name="tomo-default",
            settings={"rotation-axis": 1630.0},
            settings_schema=dict(_SETTINGS_SCHEMA),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def _revise(deps: Kernel, setup_id: UUID, axis: float, *, expected_revision: int) -> int:
    return await bind(deps)(
        ReviseSetup(
            setup_id=setup_id,
            expected_revision=expected_revision,
            settings={"rotation-axis": axis},
            settings_schema=dict(_SETTINGS_SCHEMA),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_revising_appends_the_next_revision_and_returns_its_number() -> None:
    deps = _kernel()
    setup_id = await _a_setup(deps)

    revision = await _revise(deps, setup_id, 1631.5, expected_revision=1)

    assert revision == 2
    stored, version = await deps.event_store.load(SETUP_STREAM_TYPE, setup_id)
    assert [row.event_type for row in stored] == ["SetupDefined", "SetupRevised"]
    assert stored[1].occurred_at == _CLOCK_NOW
    assert version == 2
    setup = await load_setup(deps.event_store, setup_id)
    assert setup is not None
    assert (setup.revision, setup.settings) == (2, {"rotation-axis": 1631.5})


async def test_every_earlier_revision_stays_readable_after_a_revision() -> None:
    deps = _kernel()
    setup_id = await _a_setup(deps)
    await _revise(deps, setup_id, 1631.5, expected_revision=1)
    await _revise(deps, setup_id, 1632.0, expected_revision=2)

    revisions = await load_setup_revisions(deps.event_store, setup_id)

    assert [setup.settings["rotation-axis"] for setup in revisions] == [1630.0, 1631.5, 1632.0]


async def test_a_revision_that_changes_nothing_is_refused_and_appends_nothing() -> None:
    deps = _kernel()
    setup_id = await _a_setup(deps)

    with pytest.raises(SetupCannotBeRevisedError):
        await _revise(deps, setup_id, 1630.0, expected_revision=1)

    _rows, version = await deps.event_store.load(SETUP_STREAM_TYPE, setup_id)
    assert version == 1


async def test_a_setup_id_naming_nothing_is_refused_before_the_gate_is_asked() -> None:
    """There is no beamline to ask about, which is why the read comes first."""
    authz = _OneBeamlineAuthorize("19-bm")
    deps = _kernel(authz=authz)

    with pytest.raises(SetupNotFoundError):
        await _revise(deps, uuid4(), 1631.5, expected_revision=1)

    assert authz.asked == []


async def test_the_gate_is_asked_at_the_setups_own_beamline() -> None:
    store = InMemoryEventStore()
    setup_id = await _a_setup(_kernel(event_store=store), beamline="19-bm")
    authz = _OneBeamlineAuthorize("19-bm")

    await _revise(_kernel(authz=authz, event_store=store), setup_id, 1631.5, expected_revision=1)

    assert authz.asked == [("ReviseSetup", "19-bm")]


async def test_a_caller_granted_another_beamline_cannot_revise_this_ones_setup() -> None:
    store = InMemoryEventStore()
    setup_id = await _a_setup(_kernel(event_store=store), beamline="19-bm")
    deps = _kernel(authz=_OneBeamlineAuthorize("2-bm"), event_store=store)

    with pytest.raises(UnauthorizedError, match="not granted at 19-bm"):
        await _revise(deps, setup_id, 1631.5, expected_revision=1)

    _rows, version = await store.load(SETUP_STREAM_TYPE, setup_id)
    assert version == 1


async def test_a_revision_landing_between_the_read_and_the_append_is_refused() -> None:
    """A handler holding a stale fold must lose the append, not win it, so
    two callers revising one setup leave one revision and one conflict
    rather than two revisions both numbered two."""
    store = _RacingEventStore()
    setup_id = await _a_setup(_kernel(event_store=store))
    deps = _kernel(event_store=store)

    with pytest.raises(ConcurrencyError):
        await _revise(deps, setup_id, 1631.5, expected_revision=1)

    assert store.raced, "the racing store never injected a competing write"
    revisions = await load_setup_revisions(store, setup_id)
    assert [setup.settings["rotation-axis"] for setup in revisions] == [1630.0, 9999.0]


async def test_a_caller_revising_from_a_stale_read_is_refused_and_overwrites_nothing() -> None:
    """Two callers read revision 1. The first revises; the second, still
    holding revision 1, would have written its values over the first's
    without ever seeing them. It is refused instead, told both numbers, and
    the first caller's revision is the one that stands."""
    deps = _kernel()
    setup_id = await _a_setup(deps)
    await _revise(deps, setup_id, 1631.5, expected_revision=1)

    with pytest.raises(SetupCannotBeRevisedError, match="made against revision 1") as refused:
        await _revise(deps, setup_id, 1700.0, expected_revision=1)

    assert (refused.value.revision, refused.value.expected_revision) == (2, 1)
    _rows, version = await deps.event_store.load(SETUP_STREAM_TYPE, setup_id)
    assert version == 2
    setup = await load_setup(deps.event_store, setup_id)
    assert setup is not None
    assert setup.settings == {"rotation-axis": 1631.5}


async def test_replaying_a_revision_is_refused_as_stale_rather_than_written_twice() -> None:
    """What lets this slice go without an idempotency wrapper. A replay
    carries the revision number the first attempt was made against, and
    the first attempt moved the setup past it."""
    deps = _kernel()
    setup_id = await _a_setup(deps)
    await _revise(deps, setup_id, 1631.5, expected_revision=1)

    with pytest.raises(SetupCannotBeRevisedError, match="the setup is at revision 2"):
        await _revise(deps, setup_id, 1631.5, expected_revision=1)

    revisions = await load_setup_revisions(deps.event_store, setup_id)
    assert [setup.revision for setup in revisions] == [1, 2]
