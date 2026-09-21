"""MCP door for reading a proposal.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

`run_id` comes back null while the proposal is open, which is how an
agent checking on its own advice tells whether anything came of it.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from aroc.counsel.features.get_proposal.handler import Handler
from aroc.counsel.features.get_proposal.query import GetProposal
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id


class GetProposalOutput(BaseModel):
    """A proposal as this system currently holds it."""

    proposal_id: UUID
    actor_id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    run_id: UUID | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_proposal",
        description=(
            "Read a proposal by id: which agent put it forward, the plan and "
            "values it proposes, and the run that took it if one has."
        ),
    )
    async def get_proposal_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        proposal_id: UUID,
    ) -> GetProposalOutput:
        handler = get_handler()
        proposal = await handler(
            GetProposal(proposal_id=proposal_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetProposalOutput(
            proposal_id=proposal.id,
            actor_id=proposal.actor_id,
            plan_id=proposal.plan_id,
            parameters=proposal.parameters,
            run_id=proposal.run_id,
        )
