"""HTTP door for reporting a run.

`POST /runs`, carrying the plan that was run, the parameters it was given,
and what the engine that ran it calls the result.

A POST that creates a record of something that already happened, not a
POST that makes it happen. The resource being created is the record. When
a slice that actually starts a run lands it gets its own path rather than
a flag on this one, because the two differ in what the caller is asking
for and not merely in a field.

`external_ref` is nested rather than flattened into two top-level keys, so
the body cannot express half a reference and the shape matches the value
object it becomes. The bounds on its two strings are declared here as
well as on that value object, for the reason the plan name's are: this
one turns an over-long scheme into FastAPI's standard 422 before a
command exists, and the value object is what holds for the MCP surface
and for any caller that reaches the decider another way.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from aroc.execution.features.report_run.command import ReportRun
from aroc.execution.features.report_run.handler import IdempotentHandler
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from aroc.shared.identifier import (
    IDENTIFIER_SCHEME_MAX_LENGTH,
    IDENTIFIER_VALUE_MAX_LENGTH,
    Identifier,
)


class ExternalRefBody(BaseModel):
    """What the engine that ran this calls it.

    `scheme` names the engine's own identifier vocabulary, for example
    the one a particular run engine mints its run ids under. It is open
    on purpose: which engine a deployment runs is a deployment's fact,
    not something this system should hold a list of.
    """

    scheme: str = Field(min_length=1, max_length=IDENTIFIER_SCHEME_MAX_LENGTH)
    value: str = Field(min_length=1, max_length=IDENTIFIER_VALUE_MAX_LENGTH)


class ReportRunRequest(BaseModel):
    """The run to write down.

    `parameters` is required, with no default. A run of a plan that
    constrains nothing still supplies an empty object and says so, which
    is a different fact from a caller who left the key out.
    """

    plan_id: UUID
    parameters: dict[str, Any]
    external_ref: ExternalRefBody


class ReportRunResponse(BaseModel):
    """The id of the run record that was created."""

    run_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.execution.report_run
    return handler


router = APIRouter(tags=["execution"])


@router.post(
    "/runs",
    status_code=status.HTTP_201_CREATED,
    response_model=ReportRunResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": (
                "The external reference is not well-formed, or the parameters "
                "do not satisfy the plan's schema."
            ),
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not record runs.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No plan has that id.",
        },
    },
    summary="Report a run",
)
async def post_runs(
    body: ReportRunRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same run back, not a second one.",
        ),
    ] = None,
) -> ReportRunResponse:
    run_id = await handler(
        ReportRun(
            plan_id=body.plan_id,
            parameters=body.parameters,
            external_ref=Identifier(scheme=body.external_ref.scheme, value=body.external_ref.value),
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return ReportRunResponse(run_id=run_id)
