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

The three reads go without the middle layer, because a read has nothing
to make idempotent, and so do the five run transitions and the two walk
ones: a replayed ending,
pause or resume is already refused by the domain, so the wrapper would
buy a friendlier status code for a retry rather than prevent a second
write.

Tracing wraps all ten. A query that is slow or failing is as much a
fact about the system as a write that is, and the one read that goes to
a table rather than to a stream is the one most likely to become the
slow one.

Two slices take more than the kernel. `list_runs` and `list_walks` read a projection,
which the kernel cannot hold because the kernel is declared in
infrastructure and a run summary is Execution's own idea, so this module
picks the implementation and passes it in. That is the first
deployment-shaped choice made in a bounded context rather than in
`build_kernel`, and it is here because this is where composition belongs
once the thing being composed is a context's own.

Reporting a walk takes the idempotency wrapper for the same reason
reporting a run does, and reporting one of its steps does not. The walk
mints an id here, so a retry with no key would leave a second record of
one traversal. A step names the walk and its own index, so the domain
already refuses the second one.

Recording a run takes the idempotency wrapper for the same reason
defining a plan does: the server mints the id, so a retry with no key
would leave a second record of one act. That wrapper keys on what the
caller sent, so it catches a retried REQUEST and not a re-reported RUN.
Two callers reporting the same engine run without a shared key still
make two records; see the Run state module for why that gap is open.
"""

from dataclasses import dataclass
from uuid import UUID

from aroc.execution.adapters import (
    InMemoryPlanSummaryLookup,
    InMemoryProcedureSummaryLookup,
    InMemoryRunSummaryLookup,
    InMemoryWalkSummaryLookup,
    PostgresPlanSummaryLookup,
    PostgresProcedureSummaryLookup,
    PostgresRunSummaryLookup,
    PostgresWalkSummaryLookup,
)
from aroc.execution.aggregates.plan.summary import PlanSummaryLookup
from aroc.execution.aggregates.procedure.summary import ProcedureSummaryLookup
from aroc.execution.aggregates.run.summary import RunSummaryLookup
from aroc.execution.aggregates.walk.summary import WalkSummaryLookup
from aroc.execution.features import (
    abort_run,
    complete_run,
    define_plan,
    define_procedure,
    end_walk,
    fail_run,
    get_plan,
    get_procedure,
    get_run,
    get_walk,
    list_plans,
    list_procedures,
    list_runs,
    list_walks,
    pause_run,
    report_run,
    report_step,
    report_walk,
    resume_run,
)
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.observability import with_tracing
from aroc.infrastructure.slices.idempotency import with_idempotency

_BC = "execution"


class UnreadableSummariesError(RuntimeError):
    """Startup found no way to read this context's summaries.

    Raised when there is neither a connection pool nor the in-memory event
    store, which is a combination no supported environment produces and a
    new adapter could. Failing here rather than at the first request is
    the point: a deployment that cannot answer a query should not finish
    booting and look healthy.
    """

    def __init__(self, event_store: str) -> None:
        super().__init__(
            f"No pool and no in-memory event store ({event_store}), so nothing "
            "can answer a summary query"
        )
        self.event_store = event_store


@dataclass(frozen=True)
class ExecutionHandlers:
    """The bundle, one field per slice."""

    define_plan: define_plan.IdempotentHandler
    get_plan: get_plan.Handler
    list_plans: list_plans.Handler
    define_procedure: define_procedure.IdempotentHandler
    get_procedure: get_procedure.Handler
    list_procedures: list_procedures.Handler
    report_run: report_run.IdempotentHandler
    get_run: get_run.Handler
    list_runs: list_runs.Handler
    complete_run: complete_run.Handler
    abort_run: abort_run.Handler
    fail_run: fail_run.Handler
    pause_run: pause_run.Handler
    resume_run: resume_run.Handler
    report_walk: report_walk.IdempotentHandler
    report_step: report_step.Handler
    end_walk: end_walk.Handler
    get_walk: get_walk.Handler
    list_walks: list_walks.Handler


def _run_summary_lookup(deps: Kernel) -> RunSummaryLookup:
    """Pick the read adapter this deployment can actually use.

    With a pool, the projection table, which a background worker keeps in
    step. Without one, a fold over every run stream, because the worker
    does not run when there is nothing to project into and an empty table
    would answer "no runs" while runs exist.

    The choice is here rather than in `build_kernel` because the kernel is
    declared in infrastructure and a run summary is Execution's own idea.
    This function is the first thing in this context that reads like
    composition, which is what a wire module is for.
    """
    if deps.pool is not None:
        return PostgresRunSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryRunSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def _walk_summary_lookup(deps: Kernel) -> WalkSummaryLookup:
    """Pick the read adapter for walks, the same way and for the same reason.

    A third near-identical picker rather than one generic one. What they
    share is three lines of branching; what differs is the pair of
    classes, which is the whole of what each one is for.
    """
    if deps.pool is not None:
        return PostgresWalkSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryWalkSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def _plan_summary_lookup(deps: Kernel) -> PlanSummaryLookup:
    """Pick the read adapter for plans, the same way and for the same reason.

    Two nearly identical functions rather than one generic picker. What
    they share is three lines of branching; what differs is the pair of
    classes, which is the whole of what each one is for. A shared version
    would take those as arguments and read as a factory for factories.
    """
    if deps.pool is not None:
        return PostgresPlanSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryPlanSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def _procedure_summary_lookup(deps: Kernel) -> ProcedureSummaryLookup:
    """Pick the read adapter for procedures, the same way and for the same reason."""
    if deps.pool is not None:
        return PostgresProcedureSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryProcedureSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


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
        list_plans=with_tracing(
            list_plans.bind(deps, _plan_summary_lookup(deps)),
            command_name="ListPlans",
            bc=_BC,
        ),
        define_procedure=with_tracing(
            with_idempotency(
                define_procedure.bind(deps),
                deps.idempotency_store,
                command_name="DefineProcedure",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DefineProcedure",
            bc=_BC,
        ),
        get_procedure=with_tracing(
            get_procedure.bind(deps),
            command_name="GetProcedure",
            bc=_BC,
        ),
        list_procedures=with_tracing(
            list_procedures.bind(deps, _procedure_summary_lookup(deps)),
            command_name="ListProcedures",
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
        list_runs=with_tracing(
            list_runs.bind(deps, _run_summary_lookup(deps)),
            command_name="ListRuns",
            bc=_BC,
        ),
        complete_run=with_tracing(
            complete_run.bind(deps),
            command_name="CompleteRun",
            bc=_BC,
        ),
        report_walk=with_tracing(
            with_idempotency(
                report_walk.bind(deps),
                deps.idempotency_store,
                command_name="ReportWalk",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="ReportWalk",
            bc=_BC,
        ),
        report_step=with_tracing(
            report_step.bind(deps),
            command_name="ReportWalkStep",
            bc=_BC,
        ),
        end_walk=with_tracing(
            end_walk.bind(deps),
            command_name="EndWalk",
            bc=_BC,
        ),
        get_walk=with_tracing(
            get_walk.bind(deps),
            command_name="GetWalk",
            bc=_BC,
        ),
        list_walks=with_tracing(
            list_walks.bind(deps, _walk_summary_lookup(deps)),
            command_name="ListWalks",
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


__all__ = ["ExecutionHandlers", "UnreadableSummariesError", "wire_execution"]
