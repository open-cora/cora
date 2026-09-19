"""The read handler, against in-process stores.

A read decides nothing, so what is left to check is the two things a read
can still get wrong: answering a caller who was refused, and answering
`None` where the surfaces both want a refusal.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.run import RunNotFoundError
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.define_plan import bind as bind_define_plan
from aroc.execution.features.get_run import GetRun, bind
from aroc.execution.features.report_run import ReportRun
from aroc.execution.features.report_run import bind as bind_record
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.deps import make_inmemory_kernel
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import AllowAllAuthorize, Deny
from aroc.infrastructure.ports.authorize import AuthzResult
from aroc.infrastructure.settings import Settings
from aroc.shared.identifier import Identifier
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 18, 11, 15, tzinfo=UTC)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}

_REF = Identifier(scheme="bluesky-run-uid", value="f1e2d3c4")


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
    ) -> AuthzResult:
        _ = (principal_id, command_name, surface_id)
        return Deny(reason="not on the list")


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Ids(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _a_run(deps: Kernel) -> tuple[UUID, UUID]:
    """A plan and a run of it, through the same store. Returns both ids."""
    plan_id = await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    run_id = await bind_record(deps)(
        ReportRun(plan_id=plan_id, parameters={"exposure_seconds": 0.25}, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return plan_id, run_id


async def test_reading_a_run_gives_back_what_was_recorded() -> None:
    deps = _kernel()
    plan_id, run_id = await _a_run(deps)

    run = await bind(deps)(GetRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())

    assert run.id == run_id
    assert run.plan_id == plan_id
    assert run.parameters == {"exposure_seconds": 0.25}
    assert run.external_ref == _REF


async def test_reading_a_run_that_was_never_recorded_is_refused() -> None:
    """Not `None`. Both surfaces want a refusal, so the handler raises."""
    with pytest.raises(RunNotFoundError):
        await bind(_kernel())(GetRun(run_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4())


async def test_a_denied_caller_cannot_read_a_run() -> None:
    """A read is gated too.

    A run record says what was run and with what, which is a description
    of activity rather than of configuration, so who may read one is a
    question a deployment should get to answer.
    """
    deps = _kernel()
    _plan_id, run_id = await _a_run(deps)
    refusing = bind(_kernel(authz=_DenyAllAuthorize()))

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await refusing(GetRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())
