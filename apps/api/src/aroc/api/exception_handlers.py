"""Map the errors every bounded context shares onto status codes.

Four shapes, none of them owned by a context. They are raised by the
idempotency wrapper and the event store, which every context writes
through, so a context that mounted its own copy would be declaring a
translation for machinery it does not own.

    409  ConcurrencyError
             the aggregate moved between the read and the write
         IdempotencyClaimLostError
             the same key is in flight elsewhere

    422  IdempotencyConflictError
             the same key arrived with a different body, so no cached
             answer can be the right one
         CachedHandlerError
             the status the first attempt returned, whatever it was

These lived in the Access routes module while Access was the only
context, with a note to move them when a second one needed them. The
Authority context defines a stream and so carries an idempotency key,
which is that trigger. Leaving them where they were would have left one
context's error mapping working only because a different context
happened to be mounted.

Registered once from `create_app`, alongside the auth handlers, rather
than from any `register_<bc>_routes`.
"""

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from aroc.infrastructure.ports import (
    CachedHandlerError,
    ConcurrencyError,
    IdempotencyClaimLostError,
    IdempotencyConflictError,
)
from aroc.infrastructure.slices.idempotency import classify_error_status


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

    A retried key must give back what it gave back before, including
    when that was a refusal. Returning a fresh 500 here would turn a
    deterministic 400 into a transient-looking error and invite the
    client to keep trying.
    """
    _ = request
    cached = exc.__cause__ or exc
    resolved = classify_error_status(cached) or status.HTTP_500_INTERNAL_SERVER_ERROR
    return JSONResponse(status_code=resolved, content={"detail": str(exc)})


def register_shared_exception_handlers(app: FastAPI) -> None:
    """Register the handlers no single bounded context owns."""
    app.add_exception_handler(ConcurrencyError, _handle_conflict)
    app.add_exception_handler(IdempotencyClaimLostError, _handle_conflict)
    app.add_exception_handler(IdempotencyConflictError, _handle_idempotency_conflict)
    app.add_exception_handler(CachedHandlerError, _handle_cached_failure)


__all__ = ["register_shared_exception_handlers"]
