"""HTTP door for reading one pursuit.

`GET /pursuits/{pursuit_id}`.

The response carries the whole authorization rather than a summary of it,
because every field is what somebody would be reading it to check: what
was permitted, at which beamline, over what, within what, by whom, and
whether it is still standing. A shape that left one out would send a
reader to the log.

`budget` comes back keyed by dimension, the same shape it went in as. A
list of pairs would make a client that only cares about one dimension
walk the whole thing.

The rounds come with it, the way an execution's steps come with the
execution. A summary carries a count, which says how far a pursuit has
got and not where it is: a count cannot tell an open round waiting on a
thinker from one that closed, and both leave the pursuit Running with
nothing else to distinguish them. Whatever drives a pursuit has to know
which of the two it is looking at, and the aggregate is explicit that
such a driver must survive being restarted and being duplicated, neither
of which it can do from memory. So the list is here rather than left to
be inferred.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from keeper.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)
from keeper.pursuit.aggregates.pursuit import BudgetDimension, PursuitStatus, RoundOutcome
from keeper.pursuit.features.get_pursuit.handler import Handler
from keeper.pursuit.features.get_pursuit.query import GetPursuit


class PursuitRoundResponse(BaseModel):
    """One turn of the loop: what it observed, and what became of it.

    `outcome` is null while the round is open, which is the one fact a
    count cannot carry and the reason this list exists.

    `proposal_id` and `dispatched_id` are set together and only on an
    advance. Neither appears without the other.
    """

    index: int
    execution_id: UUID
    inquiry_id: UUID
    outcome: RoundOutcome | None = None
    proposal_id: UUID | None = None
    dispatched_id: UUID | None = None


class PursuitResponse(BaseModel):
    """One pursuit, as somebody checking what it may do reads it."""

    pursuit_id: UUID
    actor_id: UUID = Field(description="Who authorized it.")
    goal: str
    beamline: str
    scopes: list[str]
    budget: dict[BudgetDimension, int]
    started_at: str
    status: PursuitStatus = Field(
        description="Running while it may still authorize work, Stopped once it may not."
    )
    stopped_by: UUID | None = Field(
        default=None,
        description="Who withdrew it, when that is how it stopped.",
    )
    rounds: list[PursuitRoundResponse] = Field(
        default_factory=list[PursuitRoundResponse],
        description="Every round it has opened, in the order it opened them.",
    )


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.pursuit.get_pursuit
    return handler


router = APIRouter(tags=["pursuit"])


@router.get(
    "/pursuits/{pursuit_id}",
    response_model=PursuitResponse,
    responses={
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not read pursuits.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No pursuit with that id.",
        },
    },
    summary="Read a pursuit",
)
async def get_pursuit(
    pursuit_id: UUID,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> PursuitResponse:
    pursuit = await handler(
        GetPursuit(pursuit_id=pursuit_id),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
    return PursuitResponse(
        pursuit_id=pursuit.id,
        actor_id=pursuit.actor_id,
        goal=pursuit.goal.value,
        beamline=pursuit.beamline.value,
        scopes=list(pursuit.scopes),
        budget=dict(pursuit.budget.limits),
        started_at=pursuit.started_at.isoformat(),
        status=pursuit.status,
        stopped_by=pursuit.stopped_by,
        rounds=[
            PursuitRoundResponse(
                index=turn.index,
                execution_id=turn.execution_id,
                inquiry_id=turn.inquiry_id,
                outcome=turn.outcome,
                proposal_id=turn.proposal_id,
                dispatched_id=turn.dispatched_id,
            )
            for turn in pursuit.rounds
        ],
    )
