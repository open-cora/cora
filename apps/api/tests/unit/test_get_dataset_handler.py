"""Reading a dataset back, against in-process stores.

A query slice, so there is nothing to decide and the cases are the three
answers it can give: the record, a refusal for an id nobody registered,
and a refusal for a caller who may not ask.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from aroc.custody.aggregates.dataset import DatasetNotFoundError
from aroc.custody.errors import UnauthorizedError
from aroc.custody.features.get_dataset import GetDataset
from aroc.custody.features.get_dataset import bind as bind_get_dataset
from aroc.custody.features.register_dataset import RegisterDataset
from aroc.custody.features.register_dataset import bind as bind_register_dataset
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

_CLOCK_NOW = datetime(2026, 9, 19, 9, 0, tzinfo=UTC)
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


async def _a_dataset(deps: Kernel) -> tuple[UUID, UUID]:
    plan_id = await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    run_id = await bind_report_run(deps)(
        ReportRun(
            plan_id=plan_id,
            parameters={},
            external_ref=Identifier(scheme="bluesky-run-uid", value="f1e2d3c4"),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    dataset_id = await bind_register_dataset(deps)(
        RegisterDataset(run_id=run_id, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return dataset_id, run_id


async def test_reading_a_registered_dataset_gives_its_run_and_reference() -> None:
    deps = _kernel()
    dataset_id, run_id = await _a_dataset(deps)

    dataset = await bind_get_dataset(deps)(
        GetDataset(dataset_id=dataset_id),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    assert dataset.id == dataset_id
    assert dataset.run_id == run_id
    assert dataset.external_ref == _REF


async def test_reading_an_unknown_id_is_not_found() -> None:
    deps = _kernel()

    with pytest.raises(DatasetNotFoundError):
        await bind_get_dataset(deps)(
            GetDataset(dataset_id=uuid4()),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_a_denied_caller_learns_nothing_about_the_dataset() -> None:
    """Reading is gated, because a record saying where a run's data is
    kept is close to the strongest thing this context can tell anybody."""
    deps = _kernel()
    dataset_id, _run_id = await _a_dataset(deps)
    denied = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError):
        await bind_get_dataset(denied)(
            GetDataset(dataset_id=dataset_id),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )
