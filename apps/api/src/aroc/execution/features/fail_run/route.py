"""HTTP door for recording that a run failed.

`POST /runs/{run_id}/fail`, with no body. The id is in the path
because it names the thing being acted on, and an ending takes no other
input.

A verb in the path, for the reason the sibling ending endpoints give:
the status is derived from the stream, so there is nothing a `PATCH`
with a status field could write.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from aroc.execution.features.fail_run.command import FailRun
from aroc.execution.features.fail_run.handler import Handler
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.fail_run
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/runs/{run_id}/fail",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not fail runs.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No run has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The run has already ended, or was changed concurrently.",
        },
    },
    summary="Record that a run failed",
)
async def post_run_fail(
    run_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        FailRun(run_id=run_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
