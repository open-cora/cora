"""HTTP door for reporting a walk.

`POST /walks`, returning the id this system minted for it. The caller
does not choose that id for the reason no caller here chooses one: an id
a caller picked is an id a caller can collide with.

The body carries the caller's own reference for the walk, which is a
different thing and is required. A walk this system cannot point back at
is a record of something that happened somewhere, with nothing to match
it against.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from aroc.execution.features.report_walk.command import ReportWalk
from aroc.execution.features.report_walk.handler import IdempotentHandler
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from aroc.shared.identifier import Identifier


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.execution.report_walk
    return handler


class ReportWalkRequest(BaseModel):
    """What the caller reports about a walk that has begun.

    `steps` is the whole list and is required, because a record given
    them one at a time cannot say how many were never reached. The bound
    is checked in the domain rather than here, so a caller sending a
    thousand and one learns the same thing over both surfaces.
    """

    reference_scheme: str
    reference_value: str
    procedure_name: str
    steps: list[str] = Field(min_length=1)
    occurred_at: datetime | None = None


class ReportWalkResponse(BaseModel):
    """The id this system minted for the walk."""

    walk_id: UUID


router = APIRouter(tags=["execution"])


@router.post(
    "/walks",
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The reference, the name, the steps or the timestamp "
            "were not ones this system will store.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not report walks.",
        },
    },
    summary="Report a walk",
)
async def post_walks(
    body: ReportWalkRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same walk back, not a second one.",
        ),
    ] = None,
) -> ReportWalkResponse:
    walk_id = await handler(
        ReportWalk(
            reference=Identifier(scheme=body.reference_scheme, value=body.reference_value),
            procedure_name=body.procedure_name,
            steps=tuple(body.steps),
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return ReportWalkResponse(walk_id=walk_id)
