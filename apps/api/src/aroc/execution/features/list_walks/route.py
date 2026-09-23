"""HTTP door for listing walks.

`GET /walks`, newest first, filterable by the reference the driver
minted. That filter is the reason the slice exists: something holding
its own reference and no walk id has nothing else to ask by.

The steps are not on these rows. A page of fifty walks carrying up to a
thousand steps each would be almost entirely steps, and how far a walk
got is two integers.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from aroc.execution.features.list_walks.handler import Handler
from aroc.execution.features.list_walks.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListWalks,
)
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.list_walks
    return handler


class WalkSummaryResponse(BaseModel):
    """A walk as a list shows it.

    `reported_count` against `step_count` is how far it got and `ended`
    says whether anything more is coming. A walk that is not ended with
    the two unequal is either still running or was abandoned, and
    nothing here can tell those apart.
    """

    walk_id: UUID
    reference_scheme: str
    reference_value: str
    procedure_name: str
    step_count: int
    reported_count: int
    ended: bool
    created_at: datetime
    updated_at: datetime


class ListWalksResponse(BaseModel):
    """One page, and the cursor that continues it."""

    items: list[WalkSummaryResponse]
    next_cursor: str | None


router = APIRouter(tags=["execution"])


@router.get(
    "/walks",
    response_model=ListWalksResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "A reference filter arrived with one half missing.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read walks.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor did not come from a previous response.",
        },
    },
    summary="List walks",
)
async def list_walks(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    reference_scheme: Annotated[str | None, Query()] = None,
    reference_value: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> ListWalksResponse:
    page = await handler(
        ListWalks.with_reference(
            scheme=reference_scheme,
            value=reference_value,
            limit=limit,
            cursor=cursor,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListWalksResponse(
        items=[
            WalkSummaryResponse(
                walk_id=summary.walk_id,
                reference_scheme=summary.reference.scheme,
                reference_value=summary.reference.value,
                procedure_name=summary.procedure_name,
                step_count=summary.step_count,
                reported_count=summary.reported_count,
                ended=summary.ended,
                created_at=summary.created_at,
                updated_at=summary.updated_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
