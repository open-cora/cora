"""HTTP door for declaring an operation's device use.

`POST /operations/{operation_id}/device-use`, carrying whether a run of it
drives devices.

A noun in the path rather than a verb, because the body says which way the
declaration goes: a pair of verbs, one for each answer, would make the
answer part of the address. The bare noun is enough, since the operation
in the path already says whose device use it is.

The field is required and has no default. An operation nobody has
declared is a third state rather than either answer, so a body that left
it out would be asking this system to pick one.

It is strict about what counts as an answer. A boolean is the whole of
the contract, and a string such as `"false"` is refused at the boundary
rather than coerced, because a declaration read the wrong way round
decides the claims of every run composed from then on.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.execution.features.declare_operation_device_use.command import (
    DeclareOperationDeviceUse,
)
from keeper.execution.features.declare_operation_device_use.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class DeclareOperationDeviceUseRequest(BaseModel):
    """Whether a run of the operation drives devices where it runs."""

    drives_devices: bool = Field(
        strict=True,
        description=(
            "True when a run of this operation drives devices at the station that "
            "runs it; false when its work happens somewhere else and touches none."
        ),
    )


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.declare_operation_device_use
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/operations/{operation_id}/device-use",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not declare device use.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No operation has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": (
                "The operation is retired, its device use is already declared, or it "
                "was declared concurrently."
            ),
        },
    },
    summary="Declare an operation's device use",
)
async def post_operation_device_use(
    operation_id: UUID,
    body: DeclareOperationDeviceUseRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        DeclareOperationDeviceUse(operation_id=operation_id, drives_devices=body.drives_devices),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
