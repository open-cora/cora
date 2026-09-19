"""The pause and resume handlers, against in-process stores.

The deciders are tested next door against states built by hand. What is
left here is what only a handler can get wrong: reading the version it
appends at, authorizing under its own command name, and writing to the
stream the command named rather than some other one.

One thing here is not a repeat of the endings file. This pair is the only
place a run takes more than one transition, so this is where a handler
that folded only the genesis instead of the whole stream would show up: a
resume decides against the state in front of it, and that state exists
only because the pause before it was read back.

The genuinely concurrent case is not here, for the reason the endings
file gives: two callers pausing at one instant both fold a running run
and both append at the same version, and only the store's unique
constraint decides between them. That lives in the integration tier.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from aroc.execution.aggregates.run import (
    RUN_STREAM_TYPE,
    RunCannotBePausedError,
    RunCannotBeResumedError,
    RunStatus,
    load_run,
)
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.abort_run import AbortRun
from aroc.execution.features.abort_run import bind as bind_abort
from aroc.execution.features.define_plan import DefinePlan
from aroc.execution.features.define_plan import bind as bind_define_plan
from aroc.execution.features.pause_run import PauseRun
from aroc.execution.features.pause_run import bind as bind_pause
from aroc.execution.features.report_run import ReportRun
from aroc.execution.features.report_run import bind as bind_report
from aroc.execution.features.resume_run import ResumeRun
from aroc.execution.features.resume_run import bind as bind_resume
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


async def test_a_pause_and_a_resume_leave_the_run_running_over_three_rows() -> None:
    """The cycle, through handlers, with the stream checked as well as the fold.

    The status alone would pass if neither handler wrote anything: the
    run starts Running and ends Running. Counting the rows is what says
    both appends happened, and reading their types is what says they
    happened in the right order.
    """
    deps = _kernel()
    run_id = await _a_run(deps)

    await bind_pause(deps)(PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())
    await bind_resume(deps)(ResumeRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())

    run = await load_run(deps.event_store, run_id)
    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)

    assert run is not None
    assert run.status is RunStatus.RUNNING
    assert [row.event_type for row in rows] == ["RunReported", "RunPaused", "RunResumed"]


async def test_a_resume_folds_the_whole_stream_and_not_only_the_genesis() -> None:
    """The handler folds the whole stream, not only the genesis.

    A handler that loaded and folded just the first row would see a
    Running run here and refuse the resume. Nothing else in this suite
    reaches two transitions deep, so nothing else could catch it.
    """
    deps = _kernel()
    run_id = await _a_run(deps)

    await bind_pause(deps)(PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())
    await bind_resume(deps)(ResumeRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())
    await bind_pause(deps)(PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())

    run = await load_run(deps.event_store, run_id)
    assert run is not None
    assert run.status is RunStatus.PAUSED


async def test_a_paused_run_can_still_be_ended() -> None:
    """Pausing does not close the stream to the three endings.

    The decider tests state this about the status; this states it about
    the path a caller actually takes, where the ending handler folds a
    paused run out of a real stream rather than being handed one.
    """
    deps = _kernel()
    run_id = await _a_run(deps)

    await bind_pause(deps)(PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())
    await bind_abort(deps)(AbortRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())

    run = await load_run(deps.event_store, run_id)
    assert run is not None
    assert run.status is RunStatus.ABORTED


async def test_a_refused_second_pause_appends_nothing() -> None:
    """A run pauses once, and a later caller leaves no trace.

    Sequential, not concurrent: the second handler loads after the first
    has appended, so it folds a paused run and its decider refuses. What
    this adds over the decider's own test is the append. A handler that
    decided correctly and wrote anyway would pass there and fail here on
    the row count.
    """
    deps = _kernel()
    run_id = await _a_run(deps)

    await bind_pause(deps)(PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4())

    with pytest.raises(RunCannotBePausedError):
        await bind_pause(deps)(
            PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert len(rows) == 2, "one genesis and exactly one pause"


async def test_a_resume_on_a_run_that_never_paused_appends_nothing() -> None:
    deps = _kernel()
    run_id = await _a_run(deps)

    with pytest.raises(RunCannotBeResumedError):
        await bind_resume(deps)(
            ResumeRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert len(rows) == 1, "the genesis and nothing else"


async def test_the_appended_event_records_the_principal_that_issued_the_command() -> None:
    deps = _kernel()
    run_id = await _a_run(deps)
    caller = uuid4()

    await bind_pause(deps)(PauseRun(run_id=run_id), principal_id=caller, correlation_id=uuid4())

    rows, _version = await deps.event_store.load(RUN_STREAM_TYPE, run_id)
    assert rows[1].principal_id == caller


async def test_each_move_authorizes_under_its_own_command_name() -> None:
    """Two verbs, two names the policy can tell apart.

    A deployment permitting an adapter to report a pause but not to
    report a resume can only express that if the two ask separately. Both
    handlers sharing one name would make that policy unwritable, and
    nothing else in the suite would notice.
    """
    refusing = _DenyAllAuthorize()
    deps = _kernel(authz=refusing)
    run_id = uuid4()

    with pytest.raises(UnauthorizedError):
        await bind_pause(deps)(
            PauseRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
        )
    with pytest.raises(UnauthorizedError):
        await bind_resume(deps)(
            ResumeRun(run_id=run_id), principal_id=uuid4(), correlation_id=uuid4()
        )

    assert refusing.asked == ["PauseRun", "ResumeRun"]


async def test_a_denied_caller_does_not_reach_the_stream() -> None:
    """Authorization comes before the load, so a refusal reveals nothing.

    A caller who may not pause runs should not be able to learn whether a
    run id exists by watching which error comes back.
    """
    deps = _kernel(authz=_DenyAllAuthorize())

    with pytest.raises(UnauthorizedError, match="not on the list"):
        await bind_pause(deps)(
            PauseRun(run_id=uuid4()), principal_id=uuid4(), correlation_id=uuid4()
        )
