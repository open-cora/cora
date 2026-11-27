"""MCP door for reading a proposal.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

`execution_id` and `step_id` come back null while the proposal is open,
which is how an agent checking on its own advice tells whether anything
came of it. Set, they name the run, and the execution is what
the agent reads to find it.

`runs` is what was put forward, always; `operation_id` and `parameters`
are the one run's for a proposal of one and null for a plan of several,
for the reason the route gives.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.counsel.aggregates.proposal import ProposalStatus
from keeper.counsel.features.get_proposal.handler import Handler
from keeper.counsel.features.get_proposal.query import GetProposal
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ProposedRunOutput(BaseModel):
    """One run the proposal puts forward, as it was proposed."""

    operation_id: UUID
    parameters: dict[str, Any]


class GetProposalOutput(BaseModel):
    """A proposal as this system currently holds it."""

    proposal_id: UUID
    actor_id: UUID
    operation_id: UUID | None
    parameters: dict[str, Any] | None
    runs: list[ProposedRunOutput]
    status: ProposalStatus
    execution_id: UUID | None
    step_id: UUID | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_proposal",
        description=(
            "Read a proposal by id: which actor put it forward, the runs it proposes in "
            "order, and the run that took it if one has. operation_id and parameters are "
            "the one run's for a proposal of one run, and null for a plan of several, "
            "whose runs are in runs."
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
        sole_run = proposal.sole_run
        return GetProposalOutput(
            proposal_id=proposal.id,
            actor_id=proposal.actor_id,
            operation_id=sole_run.operation_id if sole_run is not None else None,
            parameters=sole_run.parameters if sole_run is not None else None,
            runs=[
                ProposedRunOutput(operation_id=run.operation_id, parameters=run.parameters)
                for run in proposal.runs
            ],
            status=proposal.status,
            execution_id=proposal.execution_id,
            step_id=proposal.step_id,
        )
