"""HTTP door for registering an actor.

`POST /actors`. Returns the new id. The display name goes in and is not
echoed back: this endpoint's job is to mint an identity, and reading the
name back is the read slice's job.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from aroc.access.aggregates.actor import ACTOR_NAME_MAX_LENGTH
from aroc.access.features.register_actor.command import RegisterActor
from aroc.access.features.register_actor.handler import IdempotentHandler
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class RegisterActorRequest(BaseModel):
    """Body for creating an actor."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=ACTOR_NAME_MAX_LENGTH,
        description="Display name for the new actor.",
    )


class RegisterActorResponse(BaseModel):
    """The id of the actor that was created."""

    actor_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.access.register_actor
    return handler


router = APIRouter(tags=["access"])


@router.post(
    "/actors",
    status_code=status.HTTP_201_CREATED,
    response_model=RegisterActorResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not register actors.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "The body failed schema validation.",
        },
    },
    summary="Register an actor",
)
async def post_actors(
    body: RegisterActorRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same actor back, not a second one.",
        ),
    ] = None,
) -> RegisterActorResponse:
    actor_id = await handler(
        RegisterActor(name=body.name),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return RegisterActorResponse(actor_id=actor_id)
