"""MCP door for reporting one step of a walk.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from aroc.execution.aggregates.walk import StepOutcome
from aroc.execution.features.report_step.command import ReportWalkStep
from aroc.execution.features.report_step.handler import Handler
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id


class ReportWalkStepOutput(BaseModel):
    """The walk and the step that were reported, echoed back.

    Both, because neither alone identifies the step: an index means
    nothing without the walk it indexes into.
    """

    walk_id: UUID
    index: int


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="report_step",
        description="Record how one step of a walk ended.",
    )
    async def report_step_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        walk_id: UUID,
        index: int,
        outcome: StepOutcome,
        engine_reference: str | None = None,
        holder: str | None = None,
        overlap: list[str] | None = None,
        cause: str | None = None,
        occurred_at: datetime | None = None,
    ) -> ReportWalkStepOutput:
        handler = get_handler()
        await handler(
            ReportWalkStep(
                walk_id=walk_id,
                index=index,
                outcome=outcome,
                engine_reference=engine_reference,
                holder=holder,
                overlap=tuple(overlap) if overlap else (),
                cause=cause,
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ReportWalkStepOutput(walk_id=walk_id, index=index)
