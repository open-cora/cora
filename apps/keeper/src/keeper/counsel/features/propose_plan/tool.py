"""MCP door for proposing a plan.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

The run model is declared again here rather than imported from the
route, which is what every slice does: the two surfaces share a handler
and not a boundary.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.counsel.aggregates.proposal import PROPOSAL_MAX_RUNS, ProposedRun
from keeper.counsel.features.propose_plan.command import ProposePlan
from keeper.counsel.features.propose_plan.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ProposedRunInput(BaseModel):
    """One run of the plan: the operation, and the values to run it with."""

    operation_id: UUID
    parameters: dict[str, Any] = Field(default_factory=dict[str, Any])


class ProposePlanOutput(BaseModel):
    """What the tool hands back: the proposal the plan was recorded as."""

    proposal_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="propose_plan",
        description=(
            "Put several runs forward as one piece of advice, in the order they are meant "
            "to run: for example a collection, the transfer of its data, a reconstruction "
            "and the transfer back. Each run is an operation and the values to run it "
            "with, one to sixteen of them. Returns a proposal id, which is adopted, cited "
            "by an inquiry's answer and read back with get_proposal like any proposal. "
            "Records what was proposed, and runs nothing. Every run's values are checked "
            "against its operation's schema now; whether each step may claim devices is "
            "decided when the plan is adopted, by each operation's declared device use, "
            "and a plan citing an operation whose device use is undeclared is refused then."
        ),
    )
    async def propose_plan_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        runs: Annotated[list[ProposedRunInput], Field(min_length=1, max_length=PROPOSAL_MAX_RUNS)],
    ) -> ProposePlanOutput:
        handler = get_handler()
        proposal_id = await handler(
            ProposePlan(
                runs=tuple(
                    ProposedRun(operation_id=run.operation_id, parameters=run.parameters)
                    for run in runs
                )
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ProposePlanOutput(proposal_id=proposal_id)
