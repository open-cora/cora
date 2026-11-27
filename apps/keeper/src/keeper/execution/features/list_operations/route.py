"""HTTP door for listing operations.

`GET /operations`, newest first, filterable by name and paged with an opaque
cursor. A collection on the path the defining endpoint posts to, matching
the run list beside it.

## The one that can return two

A name is not unique here, on purpose, so this is the endpoint most likely
to hand back two rows where a caller expected one. That is the honest
answer rather than a defect: the two operations differ in what they constrain,
and which one a run cites is what says how it was constrained. A caller
that needs one operation and gets two has found something worth looking at.

## A retired operation is left out unless asked for

`include_retired=true` adds them, and every row carries a `status` either
way. Off by default, because the question a listing answers is what can
be cited, and the operation summary says why a default that listed
everything would answer a different one.

## What a row carries and what it does not

The schema is not here. It is the largest thing an operation holds and a page of
fifty would be a page of schemas; `GET /operations/{operation_id}` has it.

One timestamp rather than four. What can happen to an operation after
its definition is a declaration of its device use, one of its place use,
and its retirement, and `drives_devices`, the two place lists and the
status say whether each has.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from keeper.execution.aggregates.operation import OperationStatus
from keeper.execution.features.list_operations.handler import Handler
from keeper.execution.features.list_operations.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListOperations,
)
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class OperationSummaryResponse(BaseModel):
    """One operation, as a list shows it."""

    operation_id: UUID
    name: str
    status: OperationStatus = Field(
        description="Active, or Retired: nothing may cite a retired operation."
    )
    drives_devices: bool | None = Field(
        description=(
            "Whether a run of this operation drives devices where it runs, as the "
            "facility declared it, or null while nobody has."
        )
    )
    place_parameters: list[str] | None = Field(
        description=(
            "Which parameters of a run name a place it reads or writes data at, as the "
            "facility declared it, or null while nobody has."
        )
    )
    compute_place_parameters: list[str] | None = Field(
        description=(
            "Which parameters of a run name where it processes, declared and null "
            "together with place_parameters."
        )
    )
    created_at: datetime


class ListOperationsResponse(BaseModel):
    """A page of operations, and how to ask for the next one.

    `next_cursor` is null on the last page. It is opaque: it encodes the
    sort key of the final row, and a caller that decodes it is depending
    on an ordering this is free to change.
    """

    items: list[OperationSummaryResponse]
    next_cursor: str | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.list_operations
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/operations",
    response_model=ListOperationsResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The name filter was empty, whitespace-only or over the bound.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read operations.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor did not come from a previous response.",
        },
    },
    summary="List operations",
)
async def list_operations(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    name: Annotated[str | None, Query()] = None,
    include_retired: Annotated[
        bool,
        Query(description="Also list the operations this system has retired."),
    ] = False,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> ListOperationsResponse:
    page = await handler(
        ListOperations.with_name(
            name=name, include_retired=include_retired, limit=limit, cursor=cursor
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListOperationsResponse(
        items=[
            OperationSummaryResponse(
                operation_id=summary.operation_id,
                name=summary.name.value,
                status=summary.status,
                drives_devices=summary.drives_devices,
                place_parameters=(
                    None if summary.place_use is None else list(summary.place_use.place_parameters)
                ),
                compute_place_parameters=(
                    None
                    if summary.place_use is None
                    else list(summary.place_use.compute_place_parameters)
                ),
                created_at=summary.created_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
