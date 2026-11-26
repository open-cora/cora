"""HTTP door for defining a setup.

`POST /setups`, carrying the beamline, the operation, the name a step will
carry, the values and the schema they satisfy.

The length bounds are declared here as well as in the value objects, and
the duplication is on purpose. These turn an over-long name or beamline
into FastAPI's standard 422 alongside every other malformed-body
complaint, before a command is ever built. The ones in the value objects
are what hold for the MCP surface and for any caller that reaches the
decider another way. Neither is redundant, because neither covers the
other's callers.

The name's alphabet is NOT declared here, only described. It is checked
once, in the value object, so that one place says what a step can carry
and both surfaces get the same 400 for a name outside it.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.execution.aggregates.setup import SETUP_BEAMLINE_MAX_LENGTH, SETUP_NAME_MAX_LENGTH
from keeper.execution.features.define_setup.command import DefineSetup
from keeper.execution.features.define_setup.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class DefineSetupRequest(BaseModel):
    """The values to write down, whose they are, and what they must satisfy.

    `settings` and `settings_schema` are both required, with no default. A setup
    whose values nobody described, or a description with no values, is the
    state the aggregate exists to refuse, and obtaining it by leaving a key
    out of the body would make the refusal look like a bug in the client.
    """

    beamline: str = Field(
        min_length=1,
        max_length=SETUP_BEAMLINE_MAX_LENGTH,
        description="Which beamline holds these values, such as 2-bm. The caller is "
        "authorized against this beamline.",
    )
    operation_id: UUID = Field(
        description="The operation the setup serves. Its parameters must declare both "
        "config and override.",
    )
    name: str = Field(
        min_length=1,
        max_length=SETUP_NAME_MAX_LENGTH,
        description="What a step's config parameter will carry to name this setup: "
        "lowercase letters, digits and hyphens, unique for this operation at this beamline.",
    )
    settings: dict[str, Any] = Field(
        description="Setting name to value, as the conductor will apply them. Exactly the "
        "settings the settings schema describes.",
    )
    settings_schema: dict[str, Any] = Field(
        description="A JSON Schema in the stored subset: an object with one typed property "
        "per setting.",
    )


class DefineSetupResponse(BaseModel):
    """The id of the setup that was created."""

    setup_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.execution.define_setup
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/setups",
    status_code=status.HTTP_201_CREATED,
    response_model=DefineSetupResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The name, the beamline, the settings schema or the settings are "
            "not well-formed, or the settings do not match the schema.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not define setups at this beamline.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No operation has that id.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "The operation is retired or cannot take a setup, or another "
            "setup already holds this name for it at this beamline.",
        },
    },
    summary="Define a setup",
)
async def post_setups(
    body: DefineSetupRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same setup back, not a second one.",
        ),
    ] = None,
) -> DefineSetupResponse:
    setup_id = await handler(
        DefineSetup(
            beamline=body.beamline,
            operation_id=body.operation_id,
            name=body.name,
            settings=body.settings,
            settings_schema=body.settings_schema,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return DefineSetupResponse(setup_id=setup_id)
