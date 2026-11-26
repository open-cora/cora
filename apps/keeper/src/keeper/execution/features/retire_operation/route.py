"""HTTP door for retiring an operation.

`POST /operations/{operation_id}/retire`, carrying nothing.

An empty body, because there is nothing to say: retiring is an act
performed here, so the moment is this system's clock and there is no
field a caller could fill.

A verb in the path rather than `DELETE /operations/{operation_id}`. A
DELETE says the record is gone, and it is not: the stream stays, the
schema stays readable, and every procedure citing the operation still
resolves it. What changes is that nothing new may cite it.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from keeper.execution.features.retire_operation.command import RetireOperation
from keeper.execution.features.retire_operation.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.retire_operation
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/operations/{operation_id}/retire",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not retire operations.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No operation has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The operation is already retired, or was retired concurrently.",
        },
    },
    summary="Retire an operation",
)
async def post_operation_retire(
    operation_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        RetireOperation(operation_id=operation_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
