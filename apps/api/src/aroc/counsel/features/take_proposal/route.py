"""HTTP door for recording that a run took a proposal.

`POST /proposals/{proposal_id}/take`, carrying the run.

A verb in the path rather than `PATCH /proposals/{id}` with a run field.
The two are not equivalent: a PATCH says what the proposal should look
like afterwards and invites a caller to set or clear the run at will,
while this endpoint names one transition the domain either allows or
refuses. Whether a proposal is open is derived from the stream in any
case, so there is nothing for a PATCH to write.

The path segment is take, and not take-up. A one-word verb is not
style here: the command-to-event derivation reads only the first token
of a command name as its verb, so a phrasal verb cannot derive an event
name at all. A command named for taking up a proposal could only ever
derive an event with Up as its second token, which is why no command in
this repository is a phrasal verb.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from aroc.counsel.features.take_proposal.command import TakeProposal
from aroc.counsel.features.take_proposal.handler import Handler
from aroc.infrastructure.request import (
    ErrorResponse,
    get_correlation_id,
    get_principal_id,
    get_surface_id,
)


class TakeProposalRequest(BaseModel):
    """The run that took the proposal, and when it did.

    `run_id` is required: this endpoint exists to record a join, and a
    join with one end is nothing. `occurred_at` is optional, and omitting
    it means the event is stamped with the moment the report arrived.
    """

    run_id: UUID
    occurred_at: datetime | None = None


def _get_handler(request: Request) -> Handler:
    handler: Handler = request.app.state.counsel.take_proposal
    return handler


router = APIRouter(tags=["counsel"])


@router.post(
    "/proposals/{proposal_id}/take",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        status.HTTP_400_BAD_REQUEST: {
            "model": ErrorResponse,
            "description": "The reported timestamp carried no timezone.",
        },
        status.HTTP_403_FORBIDDEN: {
            "model": ErrorResponse,
            "description": "The calling principal may not take proposals.",
        },
        status.HTTP_404_NOT_FOUND: {
            "model": ErrorResponse,
            "description": "No proposal has that id, or no run does.",
        },
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "It was already taken, or the run ran a different plan.",
        },
    },
    summary="Record that a run took a proposal",
)
async def post_proposal_take(
    proposal_id: UUID,
    body: TakeProposalRequest,
    handler: Annotated[Handler, Depends(_get_handler)],
    cid: Annotated[UUID, Depends(get_correlation_id)],
    principal_id: Annotated[UUID, Depends(get_principal_id)],
    surface_id: Annotated[UUID, Depends(get_surface_id)],
) -> None:
    await handler(
        TakeProposal(
            proposal_id=proposal_id,
            run_id=body.run_id,
            occurred_at=body.occurred_at,
        ),
        principal_id=principal_id,
        correlation_id=cid,
        surface_id=surface_id,
    )
