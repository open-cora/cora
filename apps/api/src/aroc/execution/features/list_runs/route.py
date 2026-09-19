"""HTTP door for listing runs.

`GET /runs`, newest first, filterable by the engine's own reference for a
run and paged with an opaque cursor.

A collection on the same path the recording endpoint posts to, rather than
a route of its own such as `/runs/by-external-ref/{scheme}/{value}`. Two
reasons. A reference value is free text in the general case, and a path
segment is the one place that has to be escaped by hand; and the same
filter shape grows to answer "what ran last night" without a second
endpoint.

## What a row carries and what it does not

The parameters are not here. They are the largest thing a run holds and a
page of fifty would be mostly parameters; `GET /runs/{run_id}` has them.

The timestamps ARE here, and the single read still has none. That split is
deliberate rather than an oversight on one side: a list is read to find
something, and when it happened is how a person recognises the run they
mean. Both values are the domain time somebody reported, so a run recorded
by a backfill carries the time it ran rather than the time it was loaded.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel

from aroc.execution.aggregates.run import RunStatus
from aroc.execution.features.list_runs.handler import Handler
from aroc.execution.features.list_runs.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListRuns,
)
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


class RunSummaryResponse(BaseModel):
    """One run, as a list shows it.

    The reference pair is nested, matching the single read and the
    recording endpoint. The two filter parameters above are flat because
    a query string cannot nest, which is a fact about query strings
    rather than a second shape for the pair.
    """

    run_id: UUID
    plan_id: UUID
    external_ref: ExternalRefResponse
    status: RunStatus
    created_at: datetime
    updated_at: datetime


class ListRunsResponse(BaseModel):
    """A page of runs, and how to ask for the next one.

    `next_cursor` is null on the last page. It is opaque: it encodes the
    sort key of the final row, and a caller that decodes it is depending
    on an ordering this is free to change.
    """

    items: list[RunSummaryResponse]
    next_cursor: str | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.execution.list_runs
    return handler


router = APIRouter(tags=["execution"])


@router.get(
    "/runs",
    response_model=ListRunsResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "An external reference filter arrived with one half missing.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read runs.",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "The cursor did not come from a previous response.",
        },
    },
    summary="List runs",
)
async def list_runs(
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    external_ref_scheme: Annotated[str | None, Query()] = None,
    external_ref_value: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    cursor: Annotated[str | None, Query()] = None,
) -> ListRunsResponse:
    page = await handler(
        ListRuns.with_external_ref(
            scheme=external_ref_scheme,
            value=external_ref_value,
            limit=limit,
            cursor=cursor,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return ListRunsResponse(
        items=[
            RunSummaryResponse(
                run_id=summary.run_id,
                plan_id=summary.plan_id,
                external_ref=ExternalRefResponse(
                    scheme=summary.external_ref.scheme,
                    value=summary.external_ref.value,
                ),
                status=summary.status,
                created_at=summary.created_at,
                updated_at=summary.updated_at,
            )
            for summary in page.items
        ],
        next_cursor=page.next_cursor,
    )
