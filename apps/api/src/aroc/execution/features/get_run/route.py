"""HTTP door for reading a run.

`GET /runs/{run_id}`. Returns the id, the plan that was run, the
parameters it was given, and the engine's own reference for it.

No status field, because a run has no status yet. Nothing ends a run, so
every run this system holds is one it saw start and nothing more. The
field arrives on this response the same commit the aggregate gains it,
which is an additive change to the shape rather than a correction to it.

The parameters go back exactly as they were stored. They are the values
the engine was given, and a caller comparing them against what it asked
for has to be comparing against the record rather than a re-rendering
of it.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from aroc.execution.features.get_run.handler import Handler
from aroc.execution.features.get_run.query import GetRun
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class ExternalRefResponse(BaseModel):
    """What the engine that ran this calls it."""

    scheme: str
    value: str


class GetRunResponse(BaseModel):
    """A run as this system currently holds it."""

    run_id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    external_ref: ExternalRefResponse


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.get_run
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/runs/{run_id}",
    response_model=GetRunResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read runs.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No run has that id.",
        },
    },
    summary="Read a run",
)
async def get_run(
    run_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetRunResponse:
    run = await handler(
        GetRun(run_id=run_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetRunResponse(
        run_id=run.id,
        plan_id=run.plan_id,
        parameters=run.parameters,
        external_ref=ExternalRefResponse(
            scheme=run.external_ref.scheme,
            value=run.external_ref.value,
        ),
    )
