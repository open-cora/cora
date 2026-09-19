"""HTTP door for resuming a run.

`POST /runs/{run_id}/resume`, with no body. The id is in the path because
it names the thing being acted on, and a resume takes no other input.

A verb in the path rather than `PATCH /runs/{id}` with a status field,
for the reason the other transition routes give. This one makes the case
plainly: a PATCH setting the status back to Running would be
indistinguishable from a PATCH correcting a status somebody set wrong,
and only one of those is a thing this system models.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request, status
from pydantic import BaseModel

from aroc.execution.features.resume_run.command import ResumeRun
from aroc.execution.features.resume_run.handler import Handler
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.resume_run
    return handler


class ResumeRunRequest(BaseModel):
    """When the engine did this, if the caller knows.

    The whole body, and the whole body is optional: this endpoint took
    none at all before and a caller who has nothing to say still sends
    nothing. Omitting it means the event is stamped with the moment the
    report arrived.
    """

    occurred_at: datetime | None = None


router = APIRouter(tags=["execution"])


@router.post(
    "/runs/{run_id}/resume",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The supplied occurred_at carried no timezone.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not resume runs.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No run has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The run is not paused, or was changed concurrently.",
        },
    },
    summary="Resume a run",
)
async def post_run_resume(
    run_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    body: Annotated[ResumeRunRequest | None, Body()] = None,
) -> None:
    await handler(
        ResumeRun(
            run_id=run_id,
            occurred_at=body.occurred_at if body else None,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
