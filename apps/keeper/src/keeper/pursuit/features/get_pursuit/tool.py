"""MCP door for reading one pursuit.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The output carries the whole authorization for the reason the route's does,
and it matters more here: an agent about to act inside a pursuit reads this
to find out what it may do, so a field left off would be a permission it
cannot see.

The rounds come with it for the reason the route gives, and the same
argument applies twice over to an agent: an open round is a question
already put, and one that cannot see it would ask again.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id
from keeper.pursuit.aggregates.pursuit import BudgetDimension, PursuitStatus, RoundOutcome
from keeper.pursuit.features.get_pursuit.handler import Handler
from keeper.pursuit.features.get_pursuit.query import GetPursuit


class PursuitRoundOutput(BaseModel):
    """One turn of the loop: what it observed, and what became of it.

    `outcome` is null while the round is open, which is what tells a
    reader a question is already outstanding.
    """

    index: int
    execution_id: UUID
    inquiry_id: UUID
    outcome: RoundOutcome | None = None
    proposal_id: UUID | None = None
    dispatched_id: UUID | None = None


class GetPursuitOutput(BaseModel):
    """What the tool hands back."""

    pursuit_id: UUID
    actor_id: UUID = Field(description="Who authorized it.")
    goal: str
    beamline: str
    scopes: list[str]
    budget: dict[BudgetDimension, int]
    started_at: str
    status: PursuitStatus
    stopped_by: UUID | None = None
    rounds: list[PursuitRoundOutput] = Field(
        default_factory=list,
        description="Every round it has opened, in the order it opened them.",
    )


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_pursuit",
        description=(
            "Read one pursuit: its goal, the beamline and scopes it is "
            "authorized over, its budget, and whether it is still running. "
            "Read this before acting inside one, because these are the "
            "limits everything inside it is checked against."
        ),
    )
    async def get_pursuit_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        pursuit_id: UUID,
    ) -> GetPursuitOutput:
        handler = get_handler()
        pursuit = await handler(
            GetPursuit(pursuit_id=pursuit_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetPursuitOutput(
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
                PursuitRoundOutput(
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
