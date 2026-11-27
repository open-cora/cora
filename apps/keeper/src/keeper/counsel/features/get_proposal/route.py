"""HTTP door for reading a proposal.

`GET /proposals/{proposal_id}`. Returns who advised, what they put
forward, and the run that took it if one has.

What was put forward is `runs`, always, in order: one for a proposal made
with `POST /proposals`, as many as a plan holds for one made with
`POST /plans`. `operation_id` and `parameters` are the one run's for a
proposal of one, which is what every reader before plans read and still
reads, and null for a plan of several, which proposes no one operation.
Naming the first run there would let a reader that has not learned what a
plan is act on part of the advice as though it were all of it; a null
refuses that reader loudly instead.

For an adopted plan of several runs `step_id` is the first of its steps,
and the execution lists the rest in the order the runs were proposed.

`execution_id` and `step_id` are null while the proposal is open, and
that null is the status. There is no status field, because a two-valued
enum beside a nullable field would be the same fact written twice. A
caller asking whether a proposal is still open asks whether the step is
there.

Both ids come back, because a step is an entity inside an execution
rather than a stream of its own, so a caller given the step alone could
not read it.

The parameters come back exactly as they were stored, not re-rendered. A
caller comparing what was proposed against what an engine was given has
to be working from the record rather than from a rendering of it.

The state is folded from the stream on every call. A proposal is one row
or two, so a summary table would be machinery maintained ahead of a
need. That changes with the query this context exists for, which is
which proposals are still open, and which a fold cannot serve because it
cannot name the stream to fold.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.counsel.aggregates.proposal import ProposalStatus
from keeper.counsel.features.get_proposal.handler import Handler
from keeper.counsel.features.get_proposal.query import GetProposal
from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class ProposedRunResponse(BaseModel):
    """One run the proposal puts forward, as it was proposed."""

    operation_id: UUID
    parameters: dict[str, Any]


class GetProposalResponse(BaseModel):
    """A proposal as this system currently holds it."""

    proposal_id: UUID
    actor_id: UUID
    operation_id: UUID | None = Field(
        description="The operation of a proposal of one run, or null for a plan of several."
    )
    parameters: dict[str, Any] | None = Field(
        description="The values of a proposal of one run, or null for a plan of several."
    )
    runs: list[ProposedRunResponse] = Field(
        description="Every run the proposal puts forward, in the order they are meant to run."
    )
    status: ProposalStatus
    execution_id: UUID | None
    step_id: UUID | None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.counsel.get_proposal
    return handler


router = APIRouter(tags=["counsel"])


@router.get(
    "/proposals/{proposal_id}",
    response_model=GetProposalResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read proposals.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No proposal has that id.",
        },
    },
    summary="Read a proposal",
)
async def get_proposal(
    proposal_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> GetProposalResponse:
    proposal = await handler(
        GetProposal(proposal_id=proposal_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    sole_run = proposal.sole_run
    return GetProposalResponse(
        proposal_id=proposal.id,
        actor_id=proposal.actor_id,
        operation_id=sole_run.operation_id if sole_run is not None else None,
        parameters=sole_run.parameters if sole_run is not None else None,
        runs=[
            ProposedRunResponse(operation_id=run.operation_id, parameters=run.parameters)
            for run in proposal.runs
        ],
        status=proposal.status,
        execution_id=proposal.execution_id,
        step_id=proposal.step_id,
    )
