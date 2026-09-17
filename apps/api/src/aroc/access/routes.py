"""Mount the Access HTTP routes, and map its errors onto status codes.

The handler raises typed errors and knows nothing about HTTP. The
translation lives here, in one place, so the same handler can serve the
MCP surface where those numbers mean nothing.

Four shapes, and the reason each is what it is:

    InvalidActorNameError      400  the caller sent something we cannot
                                    accept, and sending it again will
                                    fail the same way
    UnauthorizedError          403  the caller is known and refused,
                                    which is a different fact from 401,
                                    where we do not know who is asking
    ActorAlreadyExistsError    409  the request conflicts with state
                                    that already exists
    IdempotencyClaimLostError  409  the same key is in flight elsewhere
    IdempotencyConflictError   422  the same key arrived with a different
                                    body, so no cached answer can be the
                                    right one
    CachedHandlerError         the status the first attempt returned,
                                    because a replayed key must give back
                                    what it gave back the first time

The idempotency handlers are registered here rather than centrally
because this is the first slice to use the wrapper. They move to their
own registrar the moment a second bounded context needs them, not before.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from aroc.access.aggregates.actor import ActorAlreadyExistsError, InvalidActorNameError
from aroc.access.errors import UnauthorizedError
from aroc.access.features import register_actor
from aroc.infrastructure.ports import (
    CachedHandlerError,
    IdempotencyClaimLostError,
    IdempotencyConflictError,
)
from aroc.infrastructure.slices.idempotency import classify_error_status


async def _handle_invalid_value(request: Request, exc: Exception) -> JSONResponse:
    """A value the domain refuses to accept."""
    _ = request
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": str(exc)})


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

    app.add_exception_handler(InvalidActorNameError, _handle_invalid_value)
    app.add_exception_handler(UnauthorizedError, _handle_unauthorized)
    app.add_exception_handler(ActorAlreadyExistsError, _handle_conflict)
    app.add_exception_handler(IdempotencyClaimLostError, _handle_conflict)
    app.add_exception_handler(IdempotencyConflictError, _handle_idempotency_conflict)
    app.add_exception_handler(CachedHandlerError, _handle_cached_failure)


__all__ = ["register_access_routes"]
