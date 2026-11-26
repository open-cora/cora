"""HTTP door for reading an operation.

`GET /operations/{operation_id}`. Returns the id, the name, the schema the
operation's parameters must satisfy, and whether it has been retired, which
is the whole of what an operation is.

The schema goes back exactly as it was stored, not re-rendered. A caller
generating a form or validating a request locally has to be validating
against the same document this system will validate against, and any
normalisation on the way out is a chance for the two to differ.

The state is folded from the stream on every call, and a retired operation
reads back like any other, with its status saying so. Retiring is not
deleting: a caller holding an id from a procedure composed years ago still
gets the schema that procedure was checked against.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.execution.aggregates.operation import OperationStatus
from keeper.execution.features.get_operation.handler import Handler
from keeper.execution.features.get_operation.query import GetOperation
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class GetOperationResponse(BaseModel):
    """An operation as this system currently holds it."""

    operation_id: UUID
    name: str
    parameters_schema: dict[str, Any]
    status: OperationStatus = Field(
        description="Active, or Retired: nothing may cite a retired operation."
    )


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.get_operation
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/operations/{operation_id}",
    response_model=GetOperationResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read operations.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No operation has that id.",
        },
    },
    summary="Read an operation",
)
async def get_operation(
    operation_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetOperationResponse:
    operation = await handler(
        GetOperation(operation_id=operation_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetOperationResponse(
        operation_id=operation.id,
        name=operation.name.value,
        parameters_schema=operation.parameters_schema,
        status=operation.status,
    )
