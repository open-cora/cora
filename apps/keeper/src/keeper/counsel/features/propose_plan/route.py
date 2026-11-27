"""HTTP door for proposing a plan.

`POST /plans`, carrying the runs in the order they are meant to run.

A collection of its own rather than a second body shape on
`POST /proposals`. A body that was one run or several depending on which
keys it held would make every reader of that route learn both, and the
two are refused for different things: a plan's runs are bounded and named
by their place in it. What comes back is a proposal id all the same,
because a plan is a proposal: it is read back with
`GET /proposals/{proposal_id}`, adopted at `POST /proposals/{proposal_id}/adopt`
and cited by an inquiry's answer exactly as a proposal of one run is.

There is no `GET /plans/{id}`, for that reason. A second address for one
record would be a second thing to keep answering alike.

The bound on the runs is declared here as well as in the decider, and the
duplication is the one `define_procedure` argues for: this turns a
malformed body into FastAPI's 422 before a command is built, and the
decider's refusal is what holds for the MCP surface.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, Field

from keeper.counsel.aggregates.proposal import PROPOSAL_MAX_RUNS, ProposedRun
from keeper.counsel.features.propose_plan.command import ProposePlan
from keeper.counsel.features.propose_plan.handler import IdempotentHandler
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class ProposedRunRequest(BaseModel):
    """One run of the plan: the operation, and the values to run it with.

    `parameters` defaults to empty, matching `POST /proposals`, so a run of
    a routine that takes no values sends nothing rather than an empty
    object it had to know to write.
    """

    operation_id: UUID
    parameters: dict[str, Any] = Field(default_factory=dict[str, Any])


class ProposePlanRequest(BaseModel):
    """The runs being put forward, in the order they are meant to run."""

    runs: list[ProposedRunRequest] = Field(min_length=1, max_length=PROPOSAL_MAX_RUNS)


class ProposePlanResponse(BaseModel):
    """The id of the proposal the plan was recorded as."""

    proposal_id: UUID


def _get_handler(request: Request) -> IdempotentHandler:
    handler: IdempotentHandler = request.app.state.counsel.propose_plan
    return handler


router = APIRouter(tags=["counsel"])


@router.post(
    "/plans",
    status_code=status.HTTP_201_CREATED,
    response_model=ProposePlanResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "A run's values do not satisfy its operation's schema.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not propose plans.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "A run names an operation no record has.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "A run names an operation that has been retired.",
        },
    },
    summary="Propose a plan",
)
async def post_plans(
    body: ProposePlanRequest,
    handler: Annotated[IdempotentHandler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Replay the same key to get the same proposal back, not a second one.",
        ),
    ] = None,
) -> ProposePlanResponse:
    proposal_id = await handler(
        ProposePlan(
            runs=tuple(
                ProposedRun(operation_id=run.operation_id, parameters=run.parameters)
                for run in body.runs
            )
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
        idempotency_key=idempotency_key,
    )
    return ProposePlanResponse(proposal_id=proposal_id)
