"""HTTP door for dispatching a walk.

`POST /walks`, carrying the procedure to hand out and nothing else.

The body is one field on purpose. The procedure already holds the steps,
their order and the devices each touches, so a caller that also supplied
a step list would be able to dispatch something other than what it
named, and this system would have no way to tell which it meant.

No `occurred_at`, unlike every other write on this stream. A dispatch
happens here, at the moment the record is written, so there is no
earlier instant to report. The step reports that follow do take one,
because those describe something that happened at a beamline.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel

from aroc.execution.features.dispatch_walk.command import DispatchWalk
from aroc.execution.features.dispatch_walk.handler import IdempotentHandler
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.execution.dispatch_walk
    return handler


class DispatchWalkRequest(BaseModel):
    """The procedure to hand out."""

    procedure_id: UUID


class DispatchWalkResponse(BaseModel):
    """The id of the walk that was created."""

    walk_id: UUID


router = APIRouter(tags=["execution"])


@router.post(
    "/walks",
    status_code=status.HTTP_201_CREATED,
    response_model=DispatchWalkResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The procedure's name or steps fall outside what a walk stores.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not dispatch walks.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No procedure has that id.",
        },
    },
    summary="Dispatch a walk",
)
async def post_walks(
    body: DispatchWalkRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same walk back, not a second one.",
        ),
    ] = None,
) -> DispatchWalkResponse:
    walk_id = await handler(
        DispatchWalk(procedure_id=body.procedure_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return DispatchWalkResponse(walk_id=walk_id)
