"""The recording handler, against in-process stores.

The first handler here that reads a second aggregate before deciding, so
the cases that matter are the ones about that read: that a missing plan
is the handler's refusal and not the decider's, and that the plan it
found is the one the decision actually used.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.plan import PlanNotFoundError
from aroc.execution.aggregates.run import (
    RUN_STREAM_TYPE,
    InvalidRunParametersError,
    load_run,
)
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.define_plan import bind as bind_define_plan
from aroc.execution.features.report_run import ReportRun, bind
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


class _CountingIdGenerator:
    """Hands out ids and remembers them, so a test can assert none was minted."""

    def __init__(self) -> None:
        self.issued: list[UUID] = []

    def new_id(self) -> UUID:
        minted = uuid4()
        self.issued.append(minted)
        return minted


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
        id_generator=_CountingIdGenerator(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _a_plan(deps: Kernel, schema: dict[str, Any] | None = None) -> UUID:
    return await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA if schema is None else schema),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_recording_returns_the_id_the_run_can_be_loaded_by() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)

    run_id = await bind(deps)(
        ReportRun(plan_id=plan_id, parameters={"exposure_seconds": 0.25}, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )

    run = await load_run(deps.event_store, run_id)
    assert run is not None
    assert run.id == run_id
    assert run.plan_id == plan_id
    assert run.parameters == {"exposure_seconds": 0.25}
    assert run.external_ref == _REF


async def test_naming_a_plan_that_does_not_exist_is_not_found() -> None:
    """Existence is the handler's to refuse, not the decider's.

    A 404 says the caller named something that is not there, which is a
    different answer from a plan that exists and forbids what was asked.
    The decider never sees this case, because it never gets a context.
    """
    deps = _kernel()

    with pytest.raises(PlanNotFoundError):
        await bind(deps)(
            ReportRun(plan_id=uuid4(), parameters={"exposure_seconds": 0.25}, external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_the_plan_the_handler_loaded_is_the_one_the_decision_used() -> None:
    """The cross-aggregate read, checked end to end through the handler.

    Two plans in one store with different schemas. The run names the
    strict one and sends values only the permissive one would accept. A
    handler that loaded the wrong plan, or ignored the one it loaded,
    lets this through.
    """
    deps = _kernel()
    permissive = await _a_plan(deps, {"$schema": "https://json-schema.org/draft/2020-12/schema"})
    strict = await _a_plan(deps)

    loose = await bind(deps)(
        ReportRun(plan_id=permissive, parameters={"exposure_seconds": -1}, external_ref=_REF),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    assert loose

    with pytest.raises(InvalidRunParametersError):
        await bind(deps)(
            ReportRun(plan_id=strict, parameters={"exposure_seconds": -1}, external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    plan_id = await _a_plan(deps)
    caller = uuid4()

    run_id = await bind(deps)(
        ReportRun(plan_id=plan_id, parameters={"exposure_seconds": 0.25}, external_ref=_REF),
        principal_id=caller,
        correlation_id=uuid4(),
    )

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert rows[0].event_type == "RunReported"
    assert rows[0].principal_id == caller


async def test_a_denied_caller_gets_an_error_and_reads_nothing() -> None:
    """Authorization comes before the plan is even loaded.

    A caller who may not record runs should not be able to learn whether
    a plan id exists by watching which error comes back, and the order
    in the handler is what prevents it.
    """
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind(deps)(
            ReportRun(plan_id=uuid4(), parameters={"exposure_seconds": 0.25}, external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )


async def test_refused_parameters_leave_no_stream_behind() -> None:
    """An id is spent; a stream must not be.

    A run whose genesis was refused should be absent, not present and
    empty. Loading by the minted id is the only way to tell those apart
    from outside.
    """
    deps = _kernel()
    plan_id = await _a_plan(deps)
    generator = deps.id_generator
    assert isinstance(generator, _CountingIdGenerator)
    before = len(generator.issued)

    with pytest.raises(InvalidRunParametersError):
        await bind(deps)(
            ReportRun(plan_id=plan_id, parameters={"exposure_seconds": -1}, external_ref=_REF),
            principal_id=uuid4(),
            correlation_id=uuid4(),
        )

    minted = generator.issued[before:]
    assert len(minted) == 1, "the run id was minted before the decision refused"
    assert await load_run(deps.event_store, minted[0]) is None


async def test_the_same_external_run_can_be_recorded_twice_today() -> None:
    """The known gap, asserted so it is a decision and not a surprise.

    Nothing checks that an external reference is unique across streams,
    so reporting the same engine run twice makes two records of it. This
    test exists to fail the day that changes, which is the day it should
    be read again rather than deleted.
    """
    deps = _kernel()
    plan_id = await _a_plan(deps)
    command = ReportRun(plan_id=plan_id, parameters={"exposure_seconds": 0.25}, external_ref=_REF)

    first = await bind(deps)(command, principal_id=uuid4(), correlation_id=uuid4())
    second = await bind(deps)(command, principal_id=uuid4(), correlation_id=uuid4())

    assert first != second
    one, two = await load_run(deps.event_store, first), await load_run(deps.event_store, second)
    assert one is not None
    assert two is not None
    assert one.external_ref == two.external_ref
