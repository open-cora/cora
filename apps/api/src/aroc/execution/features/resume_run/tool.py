"""MCP door for resuming a run.

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

from aroc.execution.features.resume_run.command import ResumeRun
from aroc.execution.features.resume_run.handler import Handler
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id


class ResumeRunOutput(BaseModel):
    """What the tool hands back.

    The id that was resumed, echoed so a caller chaining tools has
    something to carry forward. The HTTP route returns 204 and nothing,
    because there the id is already in the URL the caller wrote.
    """

    run_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="resume_run",
        description="Record that a run carried on from where it paused.",
    )
    async def resume_run_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        run_id: UUID,
        occurred_at: datetime | None = None,
    ) -> ResumeRunOutput:
        handler = get_handler()
        await handler(
            ResumeRun(run_id=run_id, occurred_at=occurred_at),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ResumeRunOutput(run_id=run_id)
