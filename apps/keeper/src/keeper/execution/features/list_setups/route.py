"""HTTP door for listing setups.

`GET /setups`, newest first, filterable by beamline, by operation and by
name, and paged with an opaque cursor. A collection on the path the
defining endpoint posts to, matching the other lists in this context.

## What a row carries and what it does not

The settings and their schema are not here. Either may be as large as an
operation's schema, so a page of fifty would be a page of documents, and
`GET /setups/{setup_id}` has both.

Two timestamps, unlike the operation and procedure rows beside it, because
a setup is the one record here that changes after it is defined. A row
says which revision the setup is at and when that revision was made, which
is the question a person scanning a beamline's setups has: which ones
changed, and when.

Newest first by definition rather than by revision, so a setup revised
while a caller pages through the list does not move under them.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from keeper.execution.features.list_setups.handler import Handler
from keeper.execution.features.list_setups.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListSetups,
)
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class SetupSummaryResponse(BaseModel):
    """One setup, as a list shows it."""

    setup_id: UUID
    beamline: str
    operation_id: UUID
    name: str
    revision: int = Field(description="The revision the setup is at.")
    created_at: datetime
    revised_at: datetime = Field(
        description="When the revision on this row was made; for revision 1, when the "
        "setup was defined."
    )


class ListSetupsResponse(BaseModel):
    """A page of setups, and how to ask for the next one.

    `next_cursor` is null on the last page. It is opaque: it encodes the
    sort key of the final row, and a caller that decodes it is depending
    on an ordering this is free to change.
    """

    items: list[SetupSummaryResponse]
    next_cursor: str | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.list_setups
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/setups",
    response_model=ListSetupsResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The beamline filter was empty or over the bound, or the name "
            "filter is one no setup could hold.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read setups.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor did not come from a previous response.",
        },
    },
    summary="List setups",
)
async def list_setups(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    beamline: Annotated[str | None, Query()] = None,
    operation_id: Annotated[UUID | None, Query()] = None,
    name: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> ListSetupsResponse:
    page = await handler(
        ListSetups.from_filters(
            beamline=beamline,
            operation_id=operation_id,
            name=name,
            limit=limit,
            cursor=cursor,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListSetupsResponse(
        items=[
            SetupSummaryResponse(
                setup_id=summary.setup_id,
                beamline=summary.beamline.value,
                operation_id=summary.operation_id,
                name=summary.name.value,
                revision=summary.revision,
                created_at=summary.created_at,
                revised_at=summary.revised_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
