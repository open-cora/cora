"""Compose the Execution handlers from the process-wide dependencies.

`wire_execution(deps)` runs once during startup and the bundle it returns
is attached to the app. Routes and MCP tools both pull their handler out
of that bundle, which is what keeps the two surfaces calling the same
code rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   defining a second plan
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

The two reads go without the middle layer, because a read has nothing to
make idempotent, and so do the five transitions: a replayed ending,
pause or resume is already refused by the domain, so the wrapper would
buy a friendlier status code for a retry rather than prevent a second
write.

Tracing wraps all nine. A query that is slow or failing is as much a
fact about the system as a write that is.

Recording a run takes the idempotency wrapper for the same reason
defining a plan does: the server mints the id, so a retry with no key
would leave a second record of one act. That wrapper keys on what the
caller sent, so it catches a retried REQUEST and not a re-reported RUN.
Two callers reporting the same engine run without a shared key still
make two records; see the Run state module for why that gap is open.
"""

from dataclasses import dataclass
from uuid import UUID

from aroc.execution.features import (
    abort_run,
    complete_run,
    define_plan,
    fail_run,
    get_plan,
    get_run,
    pause_run,
    report_run,
    resume_run,
)
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.observability import with_tracing
from aroc.infrastructure.slices.idempotency import with_idempotency

_BC = "execution"


@dataclass(frozen=True)
class ExecutionHandlers:
    """The bundle, one field per slice."""

    define_plan: define_plan.IdempotentHandler
    get_plan: get_plan.Handler
    report_run: report_run.IdempotentHandler
    get_run: get_run.Handler
    complete_run: complete_run.Handler
    abort_run: abort_run.Handler
    fail_run: fail_run.Handler
    pause_run: pause_run.Handler
    resume_run: resume_run.Handler


def wire_execution(deps: Kernel) -> ExecutionHandlers:
    """Build the Execution handlers."""
    return ExecutionHandlers(
        define_plan=with_tracing(
            with_idempotency(
                define_plan.bind(deps),
                deps.idempotency_store,
                command_name="DefinePlan",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DefinePlan",
            bc=_BC,
        ),
        get_plan=with_tracing(
            get_plan.bind(deps),
            command_name="GetPlan",
            bc=_BC,
        ),
        report_run=with_tracing(
            with_idempotency(
                report_run.bind(deps),
                deps.idempotency_store,
                command_name="ReportRun",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="ReportRun",
            bc=_BC,
        ),
        get_run=with_tracing(
            get_run.bind(deps),
            command_name="GetRun",
            bc=_BC,
        ),
        complete_run=with_tracing(
            complete_run.bind(deps),
            command_name="CompleteRun",
            bc=_BC,
        ),
        abort_run=with_tracing(
            abort_run.bind(deps),
            command_name="AbortRun",
            bc=_BC,
        ),
        fail_run=with_tracing(
            fail_run.bind(deps),
            command_name="FailRun",
            bc=_BC,
        ),
        pause_run=with_tracing(
            pause_run.bind(deps),
            command_name="PauseRun",
            bc=_BC,
        ),
        resume_run=with_tracing(
            resume_run.bind(deps),
            command_name="ResumeRun",
            bc=_BC,
        ),
    )


__all__ = ["ExecutionHandlers", "wire_execution"]
