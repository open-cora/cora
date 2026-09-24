"""HTTP door for reading one walk.

`GET /walks/{walk_id}`, returning the walk and every step it holds. The
only read that returns the steps: a listing drops them, because they are
the largest thing a walk carries.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from aroc.execution.aggregates.walk import StepOutcome
from aroc.execution.features.get_walk.handler import Handler
from aroc.execution.features.get_walk.query import GetWalk
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.get_walk
    return handler


class WalkStepResponse(BaseModel):
    """One step, and whichever detail its outcome carried.

    `outcome` is null for a step nothing has reported yet, which is a
    different thing from a step that was skipped. Skipped means the walk
    reached the decision and passed it over; null means nothing was ever
    said, which is what a driver that died leaves behind.
    """

    describes: str
    outcome: StepOutcome | None
    engine_reference: str | None
    cause: str | None


class GetWalkResponse(BaseModel):
    """A walk as a reader sees it, steps and all."""

    walk_id: UUID
    reference_scheme: str
    reference_value: str
    procedure_name: str
    ended: bool
    steps: list[WalkStepResponse]


router = APIRouter(tags=["execution"])


@router.get(
    "/walks/{walk_id}",
    response_model=GetWalkResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read walks.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No walk has that id.",
        },
    },
    summary="Read a walk",
)
async def get_walk(
    walk_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetWalkResponse:
    walk = await handler(
        GetWalk(walk_id=walk_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetWalkResponse(
        walk_id=walk.id,
        reference_scheme=walk.reference.scheme,
        reference_value=walk.reference.value,
        procedure_name=walk.procedure_name.value,
        ended=walk.ended,
        steps=[
            WalkStepResponse(
                describes=step.describes,
                outcome=step.outcome,
                engine_reference=step.engine_reference,
                cause=step.cause,
            )
            for step in walk.steps
        ],
    )
