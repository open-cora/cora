"""The registering handler, against in-process stores.

The first handler in this tree that reads an aggregate in another bounded
context, so the cases that matter are the ones about that read: that a
run which is not there is the handler's refusal rather than the decider's,
and that nothing is written when it fires.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from aroc.custody.aggregates.dataset import DATASET_STREAM_TYPE, load_dataset
from aroc.custody.errors import UnauthorizedError
from aroc.custody.features.register_dataset import RegisterDataset, bind
from aroc.execution.aggregates.run import RunNotFoundError
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.define_plan import bind as bind_define_plan
from aroc.execution.features.report_run import ReportRun
from aroc.execution.features.report_run import bind as bind_report_run
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.deps import make_inmemory_kernel
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import AllowAllAuthorize, Deny
from aroc.infrastructure.ports.authorize import AuthzResult
from aroc.infrastructure.settings import Settings
from aroc.shared.identifier import Identifier
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_CLOCK_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
"""What the clock says, deliberately not the time any caller reports."""
_REF = Identifier(scheme="tiled-node-path", value="raw/636de04a-2e43-4c1b")
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}


class _FixedClock:
    def now(self) -> datetime:
        return _CLOCK_NOW


class _Uuid4IdGenerator:
    def new_id(self) -> UUID:
        return uuid4()


class _DenyAllAuthorize:
    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not granted in this test")


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Uuid4IdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _a_run(deps: Kernel) -> UUID:
    """A plan and a run of it, so a dataset has something real to cite."""
    plan_id = await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await bind_report_run(deps)(
        ReportRun(
            plan_id=plan_id,
            parameters={},
            external_ref=Identifier(scheme="bluesky-run-uid", value="f1e2d3c4"),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_registering_returns_the_id_the_dataset_can_be_loaded_by() -> None:
    deps = _kernel()
    run_id = await _a_run(deps)

    dataset_id = await bind(deps)(
        RegisterDataset(run_id=run_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    dataset = await load_dataset(deps.event_store, dataset_id)
    assert dataset is not None
    assert dataset.run_id == run_id
    assert dataset.external_ref == _REF


async def test_naming_a_run_that_does_not_exist_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(RunNotFoundError):
        await bind(deps)(
            RegisterDataset(run_id=uuid4(), external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_run_that_does_not_exist_leaves_no_stream_behind() -> None:
    deps = _kernel()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)

    with pytest.raises(RunNotFoundError):
        await bind(deps)(
            RegisterDataset(run_id=uuid4(), external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    assert store.stream_ids(DATASET_STREAM_TYPE) == []


async def test_a_denied_caller_gets_an_error_and_the_run_is_never_read() -> None:
    """The gate runs before the sibling load, so a refused caller cannot
    use this slice to learn whether a run id exists."""
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await bind(deps)(
            RegisterDataset(run_id=uuid4(), external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_reported_time_is_what_the_event_carries() -> None:
    deps = _kernel()
    run_id = await _a_run(deps)
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)

    dataset_id = await bind(deps)(
        RegisterDataset(run_id=run_id, external_ref=_REF, occurred_at=_WHEN),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await store.load(DATASET_STREAM_TYPE, dataset_id)
    assert [row.occurred_at for row in rows] == [_WHEN]


async def test_omitting_the_time_stamps_the_moment_the_report_arrived() -> None:
    deps = _kernel()
    run_id = await _a_run(deps)
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)

    dataset_id = await bind(deps)(
        RegisterDataset(run_id=run_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    rows, _version = await store.load(DATASET_STREAM_TYPE, dataset_id)
    assert [row.occurred_at for row in rows] == [_CLOCK_NOW]


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    run_id = await _a_run(deps)
    principal_id = uuid4()
    store = deps.event_store
    assert isinstance(store, InMemoryEventStore)

    dataset_id = await bind(deps)(
        RegisterDataset(run_id=run_id, external_ref=_REF),
        principal_id=principal_id,
        correlation_id=uuid4(),
    )

    rows, _version = await store.load(DATASET_STREAM_TYPE, dataset_id)
    assert [row.principal_id for row in rows] == [principal_id]


async def test_two_datasets_may_cite_one_run() -> None:
    """One per run is the producer's policy, not the model's.

    Pinned here because the alternative was a stream id derived from the
    run id, which would have made one-per-run permanent from the first
    migration. It is not, so a second dataset lands on its own stream.
    """
    deps = _kernel()
    run_id = await _a_run(deps)
    handler = bind(deps)

    first = await handler(
        RegisterDataset(run_id=run_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    second = await handler(
        RegisterDataset(
            run_id=run_id,
            external_ref=Identifier(scheme="tiled-node-path", value="proc/636de04a"),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert first != second
