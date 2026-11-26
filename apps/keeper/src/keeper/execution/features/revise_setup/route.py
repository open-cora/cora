"""HTTP door for revising a setup.

`POST /setups/{setup_id}/revisions`, carrying the revision the caller read
and the whole of the new values and their schema.

A POST to a collection rather than to a verb, because each call adds one
revision to the list a setup accumulates and leaves every earlier one
readable, the way a charge is added to a pursuit. That is also why this
is a 201 where a retirement is a 204: something was created, and the
response carries the number it was given, which is the handle
`GET /setups/{setup_id}?revision=N` reads it back by.

Not a PUT or a PATCH on the setup itself. Both say the resource is
replaced or changed in place, and nothing here is: revision 1 still reads
back exactly as it was written after revision 9 lands.

`expected_revision` is required, with no default. It is the number
`GET /setups/{setup_id}` handed back, and a revision made against any
other than the latest is a 409 naming both, the precondition an `If-Match`
header would carry, written in the body where the MCP surface can carry it
too.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.execution.features.revise_setup.command import ReviseSetup
from keeper.execution.features.revise_setup.handler import Handler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class ReviseSetupRequest(BaseModel):
    """The revision this one follows, and the next revision's values and schema, both whole."""

    expected_revision: int = Field(
        ge=1,
        description="The revision this one was made against, as a read of the setup "
        "returned it. Refused when the setup is no longer at that revision.",
    )
    settings: dict[str, Any] = Field(
        description="Setting name to value, every setting and not only the ones that "
        "changed. Exactly the settings the settings schema describes.",
    )
    settings_schema: dict[str, Any] = Field(
        description="A JSON Schema in the stored subset: an object with one typed property "
        "per setting. Send the current one again if only values change.",
    )


class ReviseSetupResponse(BaseModel):
    """The setup that was revised, and the number of the revision written."""

    setup_id: UUID
    revision: int = Field(description="One more than the revision this one follows.")


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.revise_setup
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/setups/{setup_id}/revisions",
    status_code=status.HTTP_201_CREATED,
    response_model=ReviseSetupResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The settings schema or the settings are not well-formed, or "
            "the settings do not match the schema.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not revise setups at the beamline "
            "this one belongs to.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No setup has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The revision was made against a revision that is no longer "
            "the latest, it changes nothing, or the setup was revised concurrently.",
        },
    },
    summary="Revise a setup",
)
async def post_setup_revisions(
    setup_id: UUID,
    body: ReviseSetupRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> ReviseSetupResponse:
    revision = await handler(
        ReviseSetup(
            setup_id=setup_id,
            expected_revision=body.expected_revision,
            settings=body.settings,
            settings_schema=body.settings_schema,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ReviseSetupResponse(setup_id=setup_id, revision=revision)
