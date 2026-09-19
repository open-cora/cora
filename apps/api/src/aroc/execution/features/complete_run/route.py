"""HTTP door for completing a run.

`POST /runs/{run_id}/complete`, with no body. The id is in the path
because it names the thing being acted on, and an ending takes no other
input.

A verb in the path rather than `PATCH /runs/{id}` with a status field.
The two are not equivalent: a PATCH says what the run should look like
afterwards and invites a caller to set any status from any other, while
these three endpoints name three transitions the domain either allows or
refuses. The status is derived from the stream in any case, so there is
nothing for a PATCH to write.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from aroc.execution.features.complete_run.command import CompleteRun
from aroc.execution.features.complete_run.handler import Handler
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.complete_run
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/runs/{run_id}/complete",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not complete runs.",
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
    summary="Complete a run",
)
async def post_run_complete(
    run_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        CompleteRun(run_id=run_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
