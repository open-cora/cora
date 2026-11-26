"""HTTP door for reading a setup.

`GET /setups/{setup_id}`, and `GET /setups/{setup_id}?revision=N` for an
earlier revision. Returns the beamline, the operation, the name, the
revision and the whole of that revision's settings and settings schema,
which is the whole of what a setup is.

This is the only read that returns the settings and their schema. A
listing drops them, because either may be as large as an operation's
schema and a page of fifty would be a page of documents.

Both documents go back exactly as they were stored, not re-rendered. A
conductor applying the settings, or a caller checking an override against
the schema, has to be working from the record rather than from a
rendering of it.

The revision is a query parameter rather than a path segment, because it
selects a reading of one resource rather than naming another. Every
revision is the same setup, and a reader holding the setup's id already
holds everything needed to reach any of them.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from keeper.execution.features.get_setup.handler import Handler
from keeper.execution.features.get_setup.query import GetSetup
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class GetSetupResponse(BaseModel):
    """A setup as one revision of it stands."""

    setup_id: UUID
    beamline: str
    operation_id: UUID
    name: str
    revision: int = Field(
        description="Which revision this is: 1 at definition, one more for each revision."
    )
    settings: dict[str, Any]
    settings_schema: dict[str, Any]


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.get_setup
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/setups/{setup_id}",
    response_model=GetSetupResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read setups.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No setup has that id, or it has not reached that revision.",
        },
    },
    summary="Read a setup",
)
async def get_setup(
    setup_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    revision: Annotated[
        int | None,
        Query(ge=1, description="Read this revision rather than the latest."),
    ] = None,
) -> GetSetupResponse:
    setup = await handler(
        GetSetup(setup_id=setup_id, revision=revision),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return GetSetupResponse(
        setup_id=setup.id,
        beamline=setup.beamline.value,
        operation_id=setup.operation_id,
        name=setup.name.value,
        revision=setup.revision,
        settings=setup.settings,
        settings_schema=setup.settings_schema,
    )
