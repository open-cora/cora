"""Mount the Execution HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Four shapes, grouped by the answer they produce:

    400  InvalidPlanNameError
             the name was empty or too long
         InvalidPlanParametersSchemaError
             the schema is not a Draft 2020-12 document this system will
             store
         InvalidRunParametersError
             the values do not satisfy the plan's declared schema
         InvalidIdentifierError
             an external reference had an empty or over-long half

         All four say the request was never well-formed, which is a
         different fact from a request that was well-formed and refused.
         Registered through a loop rather than four calls, because the
         next member of this family should be one tuple entry.

         `InvalidIdentifierError` is the odd one: it belongs to a shared
         value object rather than to an aggregate here, so it is not
         named `Invalid<Aggregate><Field>Error` and is not defined in a
         state module. Nothing else registers it, and a shared value
         object refusing its input is still this context's 400 when this
         context is the one that built it.

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking

    404  PlanNotFoundError
             the id names no plan this system has a record of, whether
             the caller asked to read one or named one while recording
             a run
         RunNotFoundError
             the id names no run this system has a record of

    409  PlanAlreadyExistsError
         RunAlreadyExistsError
             a genesis event was asked for on a live stream
         RunCannotBeCompletedError
         RunCannotBeAbortedError
         RunCannotBeFailedError
             an ending was asked for on a run that already ended

         Five facts sharing one status, kept as separate classes because
         the caller's next move differs and because the verb in the name
         is the diagnostic. Per R6 in docs/reference/naming.md.

The concurrency and idempotency shapes are NOT here. They are cross-BC
infrastructure errors, registered once at the composition root in
`aroc.api.exception_handlers`.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from aroc.execution.aggregates.plan import (
    InvalidPlanNameError,
    InvalidPlanParametersSchemaError,
    PlanAlreadyExistsError,
    PlanNotFoundError,
)
from aroc.execution.aggregates.run import (
    InvalidRunParametersError,
    RunAlreadyExistsError,
    RunCannotBeAbortedError,
    RunCannotBeCompletedError,
    RunCannotBeFailedError,
    RunNotFoundError,
)
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features import (
    abort_run,
    complete_run,
    define_plan,
    fail_run,
    get_plan,
    get_run,
    report_run,
)
from aroc.shared.identifier import InvalidIdentifierError


async def _handle_bad_request(request: Request, exc: Exception) -> JSONResponse:
    """The request was never well-formed."""
    _ = request
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


async def _handle_unauthorized(request: Request, exc: Exception) -> JSONResponse:
    """A known caller, refused."""
    _ = request
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


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
    app.include_router(define_plan.router)
    app.include_router(get_plan.router)
    app.include_router(report_run.router)
    app.include_router(get_run.router)
    app.include_router(complete_run.router)
    app.include_router(abort_run.router)
    app.include_router(fail_run.router)

    for malformed_cls in (
        InvalidPlanNameError,
        InvalidPlanParametersSchemaError,
        InvalidRunParametersError,
        InvalidIdentifierError,
    ):
        app.add_exception_handler(malformed_cls, _handle_bad_request)
    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
    for missing_cls in (PlanNotFoundError, RunNotFoundError):
        app.add_exception_handler(missing_cls, _handle_not_found)
    for conflict_cls in (
        PlanAlreadyExistsError,
        RunAlreadyExistsError,
        RunCannotBeCompletedError,
        RunCannotBeAbortedError,
        RunCannotBeFailedError,
    ):
        app.add_exception_handler(conflict_cls, _handle_conflict)


__all__ = ["register_execution_routes"]
