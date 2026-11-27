"""Compose the Execution handlers from the process-wide dependencies.

`wire_execution(deps)` runs once during startup and the bundle it returns
is attached to the app. Routes and MCP tools both pull their handler out
of that bundle, which is what keeps the two surfaces calling the same
code rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   defining a second operation
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

The reads go without the middle layer, because a read has nothing to make
idempotent, and so do the transitions: a replayed claim, step report,
engine report, ending, retirement, revision or declaration of device use
or place use is already refused by the domain, so the wrapper would buy a friendlier
status code for a retry rather than prevent a second write.

Tracing wraps all of them. A query that is slow or failing is as much a
fact about the system as a write that is, and the reads that go to a
table rather than to a stream are the ones most likely to become the slow
ones.

Six slices take more than the kernel. The five lists read a projection,
which the kernel cannot hold because the kernel is declared in
infrastructure and an execution summary is Execution's own idea, so this
module picks the implementation and passes it in. `define_setup` takes the
setup lookup too, because it asks whether a key is already held before it
writes. That was the first deployment-shaped choice made in a bounded
context rather than in `build_kernel`, and it is here because this is
where composition belongs once the thing being composed is a context's
own.

The setup lookup is the one choice made elsewhere, in
`keeper.execution.resolving`, and this module asks for it there. Defining
a procedure and dispatching one read setups through that module with the
kernel alone, and so do the adopting slices in Counsel and Pursuit, which
this module does not build; one place making the choice is what keeps all
of them asking the same table or the same fold.

The four slices that mint an id take the idempotency wrapper: defining an
operation, defining a procedure, defining a setup, and dispatching an
execution. In each of them the server mints the id, so a retry with no key
would leave a second record of one act. Everything else names a record that
already exists, and the domain refuses the second write on its own; for a
revision, that is the refusal of one made against a revision the first
write already moved the setup past.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.execution.adapters import (
    InMemoryExecutionSummaryLookup,
    InMemoryOperationSummaryLookup,
    InMemoryProcedureSummaryLookup,
    InMemoryStepSummaryLookup,
    PostgresExecutionSummaryLookup,
    PostgresOperationSummaryLookup,
    PostgresProcedureSummaryLookup,
    PostgresStepSummaryLookup,
)
from keeper.execution.aggregates.execution.step_summary import StepSummaryLookup
from keeper.execution.aggregates.execution.summary import ExecutionSummaryLookup
from keeper.execution.aggregates.operation.summary import OperationSummaryLookup
from keeper.execution.aggregates.procedure.summary import ProcedureSummaryLookup
from keeper.execution.features import (
    claim_execution,
    declare_operation_device_use,
    declare_operation_place_use,
    define_operation,
    define_procedure,
    define_setup,
    dispatch_execution,
    end_execution,
    get_execution,
    get_operation,
    get_procedure,
    get_setup,
    list_executions,
    list_operations,
    list_procedures,
    list_setups,
    list_steps_without_datasets,
    report_step,
    report_step_run,
    retire_operation,
    retire_procedure,
    revise_setup,
)
from keeper.execution.resolving import setup_summary_lookup
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.kernel import Kernel, UnreadableSummariesError
from keeper.infrastructure.observability import with_tracing
from keeper.infrastructure.slices.idempotency import with_idempotency

_BC = "execution"


@dataclass(frozen=True)
class ExecutionHandlers:
    """The bundle, one field per slice."""

    define_operation: define_operation.IdempotentHandler
    get_operation: get_operation.Handler
    list_operations: list_operations.Handler
    retire_operation: retire_operation.Handler
    declare_operation_device_use: declare_operation_device_use.Handler
    declare_operation_place_use: declare_operation_place_use.Handler
    define_procedure: define_procedure.IdempotentHandler
    get_procedure: get_procedure.Handler
    list_procedures: list_procedures.Handler
    retire_procedure: retire_procedure.Handler
    define_setup: define_setup.IdempotentHandler
    get_setup: get_setup.Handler
    list_setups: list_setups.Handler
    revise_setup: revise_setup.Handler
    dispatch_execution: dispatch_execution.IdempotentHandler
    claim_execution: claim_execution.Handler
    report_step: report_step.Handler
    report_step_run: report_step_run.Handler
    end_execution: end_execution.Handler
    get_execution: get_execution.Handler
    list_executions: list_executions.Handler
    list_steps_without_datasets: list_steps_without_datasets.Handler


def _execution_summary_lookup(deps: Kernel) -> ExecutionSummaryLookup:
    """Pick the read adapter for executions, the same way and for the same reason.

    A third near-identical picker rather than one generic one. What they
    share is three lines of branching; what differs is the pair of
    classes, which is the whole of what each one is for.
    """
    if deps.pool is not None:
        return PostgresExecutionSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryExecutionSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def _step_summary_lookup(deps: Kernel) -> StepSummaryLookup:
    """Pick the read adapter for steps, the same way and for the same reason.

    The one pair here whose two halves reach a second context. Both do
    it without importing one: the table the Postgres half reads is kept
    by a projection subscribed to Custody's events, and the fold the
    in-memory half runs reads Custody's streams by name.
    """
    if deps.pool is not None:
        return PostgresStepSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryStepSummaryLookup(deps.event_store)
    raise UnreadableSummariesError(type(deps.event_store).__name__)


def _plan_summary_lookup(deps: Kernel) -> OperationSummaryLookup:
    """Pick the read adapter for operations, the same way and for the same reason.

    Two nearly identical functions rather than one generic picker. What
    they share is three lines of branching; what differs is the pair of
    classes, which is the whole of what each one is for. A shared version
    would take those as arguments and read as a factory for factories.
    """
    if deps.pool is not None:
        return PostgresOperationSummaryLookup(deps.pool)
    if isinstance(deps.event_store, InMemoryEventStore):
        return InMemoryOperationSummaryLookup(deps.event_store)
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
    setups = setup_summary_lookup(deps)
    return ExecutionHandlers(
        define_operation=with_tracing(
            with_idempotency(
                define_operation.bind(deps),
                deps.idempotency_store,
                command_name="DefineOperation",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DefineOperation",
            bc=_BC,
        ),
        get_operation=with_tracing(
            get_operation.bind(deps),
            command_name="GetOperation",
            bc=_BC,
        ),
        list_operations=with_tracing(
            list_operations.bind(deps, _plan_summary_lookup(deps)),
            command_name="ListOperations",
            bc=_BC,
        ),
        retire_operation=with_tracing(
            retire_operation.bind(deps),
            command_name="RetireOperation",
            bc=_BC,
        ),
        declare_operation_device_use=with_tracing(
            declare_operation_device_use.bind(deps),
            command_name="DeclareOperationDeviceUse",
            bc=_BC,
        ),
        declare_operation_place_use=with_tracing(
            declare_operation_place_use.bind(deps),
            command_name="DeclareOperationPlaceUse",
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
        retire_procedure=with_tracing(
            retire_procedure.bind(deps),
            command_name="RetireProcedure",
            bc=_BC,
        ),
        define_setup=with_tracing(
            with_idempotency(
                define_setup.bind(deps, setups),
                deps.idempotency_store,
                command_name="DefineSetup",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DefineSetup",
            bc=_BC,
        ),
        get_setup=with_tracing(
            get_setup.bind(deps),
            command_name="GetSetup",
            bc=_BC,
        ),
        list_setups=with_tracing(
            list_setups.bind(deps, setups),
            command_name="ListSetups",
            bc=_BC,
        ),
        revise_setup=with_tracing(
            revise_setup.bind(deps),
            command_name="ReviseSetup",
            bc=_BC,
        ),
        dispatch_execution=with_tracing(
            with_idempotency(
                dispatch_execution.bind(deps),
                deps.idempotency_store,
                command_name="DispatchExecution",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DispatchExecution",
            bc=_BC,
        ),
        report_step=with_tracing(
            report_step.bind(deps),
            command_name="ReportExecutionStep",
            bc=_BC,
        ),
        report_step_run=with_tracing(
            report_step_run.bind(deps),
            command_name="ReportStepRun",
            bc=_BC,
        ),
        claim_execution=with_tracing(
            claim_execution.bind(deps),
            command_name="ClaimExecution",
            bc=_BC,
        ),
        end_execution=with_tracing(
            end_execution.bind(deps),
            command_name="EndExecution",
            bc=_BC,
        ),
        get_execution=with_tracing(
            get_execution.bind(deps),
            command_name="GetExecution",
            bc=_BC,
        ),
        list_executions=with_tracing(
            list_executions.bind(deps, _execution_summary_lookup(deps)),
            command_name="ListExecutions",
            bc=_BC,
        ),
        list_steps_without_datasets=with_tracing(
            list_steps_without_datasets.bind(deps, _step_summary_lookup(deps)),
            command_name="ListStepsWithoutDatasets",
            bc=_BC,
        ),
    )


__all__ = ["ExecutionHandlers", "wire_execution"]
