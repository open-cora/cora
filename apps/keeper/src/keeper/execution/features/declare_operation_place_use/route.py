"""HTTP door for declaring an operation's place use.

`POST /operations/{operation_id}/place-use`, carrying the parameters of a
run that name a place and the ones that name where it processes.

A noun in the path, beside the device use door, because the body is the
declaration and the operation in the path already says whose it is.

Both lists are required and neither has a default. Empty is an answer,
that the operation's runs name no place of that kind, and a body that
left a list out would be asking this system to give that answer for it.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.execution.aggregates.operation import PlaceUse
from keeper.execution.features.declare_operation_place_use.command import (
    DeclareOperationPlaceUse,
)
from keeper.execution.features.declare_operation_place_use.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class DeclareOperationPlaceUseRequest(BaseModel):
    """Which parameters of a run of the operation name a place."""

    place_parameters: list[str] = Field(
        description=(
            "The parameters naming a place a run reads or writes data at, such as "
            "both ends of a move. Empty when its runs name none."
        ),
    )
    compute_place_parameters: list[str] = Field(
        description=(
            "The parameters naming where a run processes, such as the place a "
            "process runs at. Empty when its runs process nowhere."
        ),
    )


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.declare_operation_place_use
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/operations/{operation_id}/place-use",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": (
                "A parameter is named twice, or is not one the operation's schema declares as text."
            ),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not declare place use.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No operation has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "The operation is retired, its place use is already declared, or it "
                "was declared concurrently."
            ),
        },
    },
    summary="Declare an operation's place use",
)
async def post_operation_place_use(
    operation_id: UUID,
    body: DeclareOperationPlaceUseRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        DeclareOperationPlaceUse(
            operation_id=operation_id,
            place_use=PlaceUse(
                place_parameters=tuple(body.place_parameters),
                compute_place_parameters=tuple(body.compute_place_parameters),
            ),
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
