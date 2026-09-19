"""The three ending handlers, against in-process stores.

The deciders are tested next door against states built by hand. What is
left here is what only a handler can get wrong: reading the version it
appends at, authorizing under its own command name, and writing to the
stream the command named rather than some other one.

The genuinely concurrent case is not here. Two callers ending one run at
the same instant both fold a running run and both append at the same
version, and only the store's unique constraint decides between them.
That cannot be staged against an in-memory store that serialises with a
lock, so it lives in the integration tier, which is where Access puts
its own.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.run import (
    RUN_STREAM_TYPE,
    RunCannotBeAbortedError,
    RunStatus,
    load_run,
)
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.abort_run import AbortRun
from aroc.execution.features.abort_run import bind as bind_abort
from aroc.execution.features.complete_run import CompleteRun
from aroc.execution.features.complete_run import bind as bind_complete
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.define_plan import bind as bind_define_plan
from aroc.execution.features.fail_run import FailRun
from aroc.execution.features.fail_run import bind as bind_fail
from aroc.execution.features.report_run import ReportRun
from aroc.execution.features.report_run import bind as bind_report
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.deps import make_inmemory_kernel
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import AllowAllAuthorize, Deny
from aroc.infrastructure.ports.authorize import AuthzResult
from aroc.infrastructure.settings import Settings
from aroc.shared.identifier import Identifier
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


class _FixedClock:
    def now(self) -> datetime:
        return _WHEN


class _Ids:
    def new_id(self) -> UUID:
        return uuid4()


class _DenyAllAuthorize:
    """Refuses everything, and remembers what it was asked about."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        _ = (principal_id, surface_id)
        self.asked.append(command_name)
        return Deny(reason="not on the list")


def _kernel(*, authz: object | None = None) -> Kernel:
    return make_inmemory_kernel(
        settings=Settings(app_env="test"),
        clock=_FixedClock(),
        id_generator=_Ids(),
        authz=authz or AllowAllAuthorize(),  # pyright: ignore[reportArgumentType]
        event_store=InMemoryEventStore(),
    )


async def _a_run(deps: Kernel, value: str = "f1e2d3c4") -> UUID:
    """A plan and a run of it, through the same store. Returns the run id."""
    plan_id = await bind_define_plan(deps)(
        DefinePlan(name="count", parameters_schema=_SCHEMA),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )
    return await bind_report(deps)(
        ReportRun(
            plan_id=plan_id,
            parameters={"exposure_seconds": 0.25},
            external_ref=Identifier(scheme="bluesky-run-uid", value=value),
        ),
        principal_id=uuid4(),
        correlation_id=uuid4(),
    )


async def test_completing_a_run_moves_it_to_completed() -> None:
    deps = _kernel()
    run_id = await _a_run(deps)

    await bind_complete(deps)(
        CompleteRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    run = await load_run(deps.event_store, run_id)
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_each_ending_writes_its_own_event_onto_the_runs_stream() -> None:
    """One store, three runs, three different second rows.

    Reading the raw event types rather than the folded status, because
    the fold is what the decider test already covers. What this adds is
    that the handler appended to the stream the command named and wrote
    the class its own decider returned.
    """
    deps = _kernel()
    completing = await _a_run(deps, "uid-completing")
    aborting = await _a_run(deps, "uid-aborting")
    failing = await _a_run(deps, "uid-failing")

    await bind_complete(deps)(
        CompleteRun(run_id=completing), principal_id=uuid4(), correlation_id=uuid4()
    )
    await bind_abort(deps)(AbortRun(run_id=aborting), principal_id=uuid4(), correlation_id=uuid4())
    await bind_fail(deps)(FailRun(run_id=failing), principal_id=uuid4(), correlation_id=uuid4())

    written: list[str] = []
    for run_id in (completing, aborting, failing):
        rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
        assert rows[0].event_type == "RunReported"
        written.append(rows[1].event_type)

    assert written == ["RunCompleted", "RunAborted", "RunFailed"]


async def test_a_refused_second_ending_appends_nothing() -> None:
    """A run ends once, and a later caller leaves no trace.

    Sequential, not concurrent: the second handler loads after the first
    has appended, so it folds an ended run and its decider refuses. The
    genuinely simultaneous case, where both fold a RUNNING run and race
    to append at the same version, cannot be staged against a store that
    serialises with a lock; it lives in the integration tier against real
    SQL, where the unique constraint is what decides.

    What this adds over the decider's own test is the append. A handler
    that decided correctly and wrote anyway would pass there and fail
    here on the row count.
    """
    deps = _kernel()
    run_id = await _a_run(deps)

    await bind_complete(deps)(
        CompleteRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
    )

    with pytest.raises(RunCannotBeAbortedError):
        await bind_abort(deps)(
            AbortRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert len(rows) == 2, "one genesis and exactly one ending"


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    run_id = await _a_run(deps)
    caller = uuid4()

    await bind_fail(deps)(FailRun(run_id=run_id), principal_id=caller, correlation_id=uuid4())

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert rows[1].principal_id == caller


async def test_each_ending_authorizes_under_its_own_command_name() -> None:
    """Three verbs, three names the policy can tell apart.

    A deployment permitting a read-only feed to complete runs but not
    abort them can only express that if the three ask separately. All
    three handlers sharing one name would make that policy unwritable,
    and nothing else in the suite would notice.
    """
    refusing = _DenyAllAuthorize()
    deps = _kernel(authz=refusing)
    run_id = uuid4()

    for handler, command in (
        (bind_complete(deps), CompleteRun(run_id=run_id)),
        (bind_abort(deps), AbortRun(run_id=run_id)),
        (bind_fail(deps), FailRun(run_id=run_id)),
    ):
        with pytest.raises(UnauthorizedError):
            await handler(command, principal_id=uuid4(), correlation_id=uuid4())  # pyright: ignore[reportArgumentType]

    assert refusing.asked == ["CompleteRun", "AbortRun", "FailRun"]


async def test_a_denied_caller_does_not_reach_the_stream() -> None:
    """Authorization comes before the load, so a refusal reveals nothing.

    A caller who may not end runs should not be able to learn whether a
    run id exists by watching which error comes back.
    """
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind_complete(deps)(
            CompleteRun(run_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )
