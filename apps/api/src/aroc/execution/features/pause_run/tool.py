"""MCP door for pausing a run.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from aroc.execution.features.pause_run.command import PauseRun
from aroc.execution.features.pause_run.handler import Handler
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id


class PauseRunOutput(BaseModel):
    """What the tool hands back.

    The id that was paused, echoed so a caller chaining tools has
    something to carry forward. The HTTP route returns 204 and nothing,
    because there the id is already in the URL the caller wrote.
    """

    run_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="pause_run",
        description="Record that a run stopped where it was and can carry on.",
    )
    async def pause_run_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        run_id: UUID,
    ) -> PauseRunOutput:
        handler = get_handler()
        await handler(
            PauseRun(run_id=run_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return PauseRunOutput(run_id=run_id)
