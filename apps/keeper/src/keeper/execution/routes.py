"""Mount the Execution HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Four shapes, grouped by the answer they produce:

    400  InvalidOperationNameError
             the name was empty or too long
         InvalidOperationParametersSchemaError
             the schema is not a Draft 2020-12 document this system will
             store
         InvalidOperationPlaceUseError
             a declaration of place use named a parameter twice, or one
             the operation's schema does not declare as text
         InvalidProcedureNameError
         InvalidProcedureBeamlineError
         InvalidProcedureStepsError
         InvalidProcedureParametersError
             a procedure was composed with a name, a beamline, a step
             list or a set of run parameters this system will
             not store, a run's among them naming a setup the
             beamline does not hold or overriding one with a setting
             it does not describe
         InvalidSetupNameError
         InvalidSetupBeamlineError
         InvalidSetupSettingsError
         InvalidSetupSettingsSchemaError
             a setup was given a name a step could not carry, a beamline,
             a settings schema this system will not store, or settings
             that do not match their schema
         InvalidIdentifierError
             an external reference had an empty or over-long half
         InvalidOccurredAtError
             a reported timestamp carried no timezone, so the instant it
             names cannot be known
         InvalidStepReportError
             a step report carried a detail belonging to a different
             outcome

         All of them say the request was never well-formed, which is a
         different fact from a request that was well-formed and refused.
         Registered through a loop rather than one call each, because the
         next member of this family should be one tuple entry.

         `InvalidIdentifierError` is the odd one: it belongs to a shared
         value object rather than to an aggregate here, so it is not
         named `Invalid<Aggregate><Field>Error` and is not defined in a
         state module. Nothing else registers it, and a shared value
         object refusing its input is still this context's 400 when this
         context is the one that built it.

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking. Registered in
             `keeper.api.exception_handlers` rather than here: the class
             is shared by every context, so one mapping serves them all

    404  OperationNotFoundError
             the id names no operation this system has a record of, whether
             the caller asked to read one or named one in a procedure
         ProcedureNotFoundError
             a dispatch named a routine nobody composed
         ProcedureStepNotFoundError
             a step of an execution cites a composed step its procedure
             does not hold
         ExecutionNotFoundError
         ExecutionStepNotFoundError
         ExecutionStepOutOfRangeError
             the id names no execution, or that execution holds no such
             step, by id or by index
         SetupNotFoundError
         SetupRevisionNotFoundError
             the id names no setup, or that setup has not reached the
             revision a read asked for

    409  OperationAlreadyExistsError
         ProcedureAlreadyExistsError
         ExecutionAlreadyExistsError
             a genesis event was asked for on a live stream
         SetupAlreadyExistsError
             the same, for a setup, and also a second definition under a
             key one setup already holds
         OperationCannotBeRetiredError
         ProcedureCannotBeRetiredError
             a retirement arrived for a record already retired
         OperationCannotBeCitedError
             something new named an operation that has been retired:
             a procedure, a proposal, a setup, or a dispatch of a
             procedure that runs it. Counsel raises it too, and relies on
             this registration rather than repeating it
         OperationDeviceUseCannotBeDeclaredError
         OperationPlaceUseCannotBeDeclaredError
             a declaration of device use or of place use arrived for an
             operation that is retired or declared already
         OperationCannotBeComposedError
             a run composed for a proposal met the operation's device
             use: undeclared in a composition of several runs, or
             declared to drive devices and asked to drive none. Counsel
             and Pursuit raise it through the composing seam, and rely
             on this registration rather than repeating it
         OperationCannotTakeSetupError
             a setup was defined for an operation whose parameters do not
             let a run of it name one
         SetupCannotBeRevisedError
             a revision was made against a revision that is no longer
             the latest, or changed nothing
         SetupCannotBePinnedError
             a dispatch found no setup holding the name a run carries
             at the procedure's beamline, or the run's override no
             longer fits the setup's latest revision
         ProcedureCannotBeDispatchedError
             a dispatch named a procedure that has been retired
         ExecutionAlreadyEndedError
             something arrived for an execution that had closed
         ExecutionCannotBeClaimedError
             a claim arrived for an execution not waiting to be taken up
         ExecutionCannotBeParkedError
             a parking arrived for an execution parked already, or one
             whose last reported step handed nothing off to wait on
         ExecutionStepAlreadyReportedError
             a step already has an outcome, and it ends exactly once
         ExecutionStepCannotBeReportedError
             a step report arrived for an execution that is parked
         StepRunCannotBeReportedError
             the engine report does not follow the one before it

         Several facts sharing one status, kept as separate classes
         because the caller's next move differs and because the verb in
         the name is the diagnostic. Per R6 in docs/reference/naming.md.

The concurrency and idempotency shapes are NOT here. They are cross-BC
infrastructure errors, registered once at the composition root in
`keeper.api.exception_handlers`.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from keeper.execution.aggregates.execution import (
    ExecutionAlreadyEndedError,
    ExecutionAlreadyExistsError,
    ExecutionCannotBeClaimedError,
    ExecutionCannotBeParkedError,
    ExecutionNotFoundError,
    ExecutionStepAlreadyReportedError,
    ExecutionStepCannotBeReportedError,
    ExecutionStepNotFoundError,
    ExecutionStepOutOfRangeError,
    InvalidExecutionBeamlineError,
    InvalidExecutionProcedureNameError,
    InvalidExecutionStepsError,
    InvalidStepReportError,
    StepRunCannotBeReportedError,
)
from keeper.execution.aggregates.operation import (
    InvalidOperationNameError,
    InvalidOperationParametersSchemaError,
    InvalidOperationPlaceUseError,
    OperationAlreadyExistsError,
    OperationCannotBeCitedError,
    OperationCannotBeComposedError,
    OperationCannotBeRetiredError,
    OperationDeviceUseCannotBeDeclaredError,
    OperationNotFoundError,
    OperationPlaceUseCannotBeDeclaredError,
)
from keeper.execution.aggregates.procedure import (
    InvalidProcedureBeamlineError,
    InvalidProcedureNameError,
    InvalidProcedureParametersError,
    InvalidProcedureStepsError,
    ProcedureAlreadyExistsError,
    ProcedureCannotBeDispatchedError,
    ProcedureCannotBeRetiredError,
    ProcedureNotFoundError,
    ProcedureStepNotFoundError,
)
from keeper.execution.aggregates.setup import (
    InvalidSetupBeamlineError,
    InvalidSetupNameError,
    InvalidSetupSettingsError,
    InvalidSetupSettingsSchemaError,
    OperationCannotTakeSetupError,
    SetupAlreadyExistsError,
    SetupCannotBePinnedError,
    SetupCannotBeRevisedError,
    SetupNotFoundError,
    SetupRevisionNotFoundError,
)
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
    park_execution,
    report_step,
    report_step_run,
    retire_operation,
    retire_procedure,
    revise_setup,
)
from keeper.shared.identifier import InvalidIdentifierError
from keeper.shared.instant import InvalidOccurredAtError


async def _handle_bad_request(request: Request, exc: Exception) -> JSONResponse:
    """The request was never well-formed."""
    _ = request
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


async def _handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    """The id names nothing this system has a record of."""
    _ = request
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _handle_conflict(request: Request, exc: Exception) -> JSONResponse:
    """The request disagrees with state that is already there."""
    _ = request
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


def register_execution_routes(app: FastAPI) -> None:
    """Include every Execution router and register its exception handlers."""
    app.include_router(define_operation.router)
    app.include_router(get_operation.router)
    app.include_router(list_operations.router)
    app.include_router(retire_operation.router)
    app.include_router(declare_operation_device_use.router)
    app.include_router(declare_operation_place_use.router)
    app.include_router(dispatch_execution.router)
    app.include_router(claim_execution.router)
    app.include_router(report_step.router)
    app.include_router(report_step_run.router)
    app.include_router(park_execution.router)
    app.include_router(end_execution.router)
    app.include_router(get_execution.router)
    app.include_router(list_executions.router)
    app.include_router(define_procedure.router)
    app.include_router(get_procedure.router)
    app.include_router(list_procedures.router)
    app.include_router(retire_procedure.router)
    app.include_router(define_setup.router)
    app.include_router(get_setup.router)
    app.include_router(list_setups.router)
    app.include_router(revise_setup.router)
    app.include_router(list_steps_without_datasets.router)

    for malformed_cls in (
        InvalidOperationNameError,
        InvalidOperationParametersSchemaError,
        InvalidOperationPlaceUseError,
        InvalidProcedureNameError,
        InvalidProcedureBeamlineError,
        InvalidProcedureParametersError,
        InvalidProcedureStepsError,
        InvalidIdentifierError,
        InvalidOccurredAtError,
        InvalidStepReportError,
        InvalidExecutionBeamlineError,
        InvalidExecutionProcedureNameError,
        InvalidExecutionStepsError,
        InvalidSetupNameError,
        InvalidSetupBeamlineError,
        InvalidSetupSettingsSchemaError,
        InvalidSetupSettingsError,
    ):
        app.add_exception_handler(malformed_cls, _handle_bad_request)
    for missing_cls in (
        OperationNotFoundError,
        ProcedureNotFoundError,
        ProcedureStepNotFoundError,
        ExecutionNotFoundError,
        ExecutionStepNotFoundError,
        ExecutionStepOutOfRangeError,
        SetupNotFoundError,
        SetupRevisionNotFoundError,
    ):
        app.add_exception_handler(missing_cls, _handle_not_found)
    for conflict_cls in (
        OperationAlreadyExistsError,
        ProcedureAlreadyExistsError,
        ExecutionAlreadyExistsError,
        OperationCannotBeRetiredError,
        ProcedureCannotBeRetiredError,
        OperationCannotBeCitedError,
        OperationDeviceUseCannotBeDeclaredError,
        OperationPlaceUseCannotBeDeclaredError,
        OperationCannotBeComposedError,
        ProcedureCannotBeDispatchedError,
        ExecutionAlreadyEndedError,
        ExecutionCannotBeClaimedError,
        ExecutionCannotBeParkedError,
        ExecutionStepAlreadyReportedError,
        ExecutionStepCannotBeReportedError,
        StepRunCannotBeReportedError,
        SetupAlreadyExistsError,
        OperationCannotTakeSetupError,
        SetupCannotBeRevisedError,
        SetupCannotBePinnedError,
    ):
        app.add_exception_handler(conflict_cls, _handle_conflict)


__all__ = ["register_execution_routes"]
