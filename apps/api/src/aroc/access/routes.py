"""Mount the Access HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Eight shapes, grouped by the answer they produce:

    403  UnauthorizedError
             the caller is known and refused, which is a different fact
             from 401, where we do not know who is asking

    404  ActorNotFoundError
             the id names no actor this system has a record of

    409  ActorAlreadyExistsError
             a genesis event was asked for on a live stream
         ActorCannotBeDeactivatedError
             the actor is there and is already switched off
         ConcurrencyError
             the actor moved between the read and the write
         IdempotencyClaimLostError
             the same key is in flight elsewhere

         Four different facts sharing one status. They are separate
         classes because the caller's next move differs: retry, stop,
         re-read, or wait.

    422  IdempotencyConflictError
             the same key arrived with a different body, so no cached
             answer can be the right one

         CachedHandlerError
             the status the first attempt returned, whatever it was,
             because a replayed key must give back what it gave back

The idempotency handlers are registered here rather than centrally
because this is the first slice to use the wrapper. They move to their
own registrar the moment a second bounded context needs them, not before.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from aroc.access.aggregates.actor import (
    ActorAlreadyExistsError,
    ActorCannotBeDeactivatedError,
    ActorNotFoundError,
)
from aroc.access.errors import UnauthorizedError
from aroc.access.features import deactivate_actor, register_actor
from aroc.infrastructure.ports import (
    CachedHandlerError,
    ConcurrencyError,
    IdempotencyClaimLostError,
    IdempotencyConflictError,
)
from aroc.infrastructure.slices.idempotency import classify_error_status


async def _handle_not_found(request: Request, exc: Exception) -> JSONResponse:
    """The id names nothing this system has a record of."""
    _ = request
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


async def _handle_unauthorized(request: Request, exc: Exception) -> JSONResponse:
    """A known caller, refused."""
    _ = request
    return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": str(exc)})


async def _handle_conflict(request: Request, exc: Exception) -> JSONResponse:
    """The request disagrees with state that is already there."""
    _ = request
    return JSONResponse(status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)})


async def _handle_idempotency_conflict(request: Request, exc: Exception) -> JSONResponse:
    """The same key, a different body. No cached answer can be correct."""
    _ = request
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content={"detail": str(exc)}
    )


async def _handle_cached_failure(request: Request, exc: Exception) -> JSONResponse:
    """Replay the failure the first attempt produced, with its own status.

    A retried key must give back what it gave back before, including when
    that was a refusal. Returning a fresh 500 here would turn a
    deterministic 400 into a transient-looking error and invite the client
    to keep trying.
    """
    _ = request
    cached = exc.__cause__ or exc
    resolved = classify_error_status(cached) or status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(status_code=resolved, content={"detail": str(exc)})


def register_access_routes(app: FastAPI) -> None:
    """Include every Access router and register its exception handlers."""
    app.include_router(register_actor.router)
    app.include_router(deactivate_actor.router)

    app.add_exception_handler(ActorNotFoundError, _handle_not_found)
    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
    app.add_exception_handler(ActorAlreadyExistsError, _handle_conflict)
    app.add_exception_handler(ActorCannotBeDeactivatedError, _handle_conflict)
    app.add_exception_handler(ConcurrencyError, _handle_conflict)
    app.add_exception_handler(IdempotencyClaimLostError, _handle_conflict)
    app.add_exception_handler(IdempotencyConflictError, _handle_idempotency_conflict)
    app.add_exception_handler(CachedHandlerError, _handle_cached_failure)


__all__ = ["register_access_routes"]
