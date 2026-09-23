"""HTTP door for reporting one step of a walk.

`POST /walks/{walk_id}/steps`, with the step's place in the list in the
body rather than in the path. A step has no id of its own and the index
is not a resource address: it names a slot the genesis already created,
which posting to the collection fills rather than creates.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from aroc.execution.aggregates.walk import StepOutcome
from aroc.execution.features.report_step.command import ReportWalkStep
from aroc.execution.features.report_step.handler import Handler
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.report_step
    return handler


class ReportWalkStepRequest(BaseModel):
    """How one step ended, and whichever detail its outcome carries.

    The three detail fields are all optional here and checked against
    the outcome in the domain, so a caller sending a cause alongside a
    done step is refused with the same message over both surfaces
    rather than by a schema on one of them.
    """

    index: int = Field(ge=0)
    outcome: StepOutcome
    engine_reference: str | None = None
    holder: str | None = None
    overlap: list[str] = Field(default_factory=list[str])
    cause: str | None = None
    occurred_at: datetime | None = None


router = APIRouter(tags=["execution"])


@router.post(
    "/walks/{walk_id}/steps",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The details did not belong to the outcome reported, "
            "or the timestamp carried no timezone.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not report walk steps.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No walk has that id, or it has no step at that index.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The walk has ended, the step already has an outcome, "
            "or the walk was changed concurrently.",
        },
    },
    summary="Report one step of a walk",
)
async def post_walk_steps(
    walk_id: UUID,
    body: ReportWalkStepRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        ReportWalkStep(
            walk_id=walk_id,
            index=body.index,
            outcome=body.outcome,
            engine_reference=body.engine_reference,
            holder=body.holder,
            overlap=tuple(body.overlap),
            cause=body.cause,
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
