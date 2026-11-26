"""HTTP door for retiring a procedure.

`POST /procedures/{procedure_id}/retire`, carrying nothing.

An empty body, because there is nothing to say. The moment is this
system's clock, and the beamline the retirement is authorized against is
the procedure's own, read off its record rather than taken from the
caller.

A verb in the path rather than `DELETE /procedures/{procedure_id}`. A
DELETE says the record is gone, and it is not: the steps stay readable
and every execution that cites one still resolves it. What changes is
that a dispatch of it is refused.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from keeper.execution.features.retire_procedure.command import RetireProcedure
from keeper.execution.features.retire_procedure.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.retire_procedure
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/procedures/{procedure_id}/retire",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not retire procedures at the "
            "beamline this one runs at.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No procedure has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The procedure is already retired, or was retired concurrently.",
        },
    },
    summary="Retire a procedure",
)
async def post_procedure_retire(
    procedure_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        RetireProcedure(procedure_id=procedure_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
