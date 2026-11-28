"""MCP door for parking an execution.

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

from keeper.execution.features.park_execution.command import ParkExecution
from keeper.execution.features.park_execution.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ParkExecutionOutput(BaseModel):
    """The id that was parked, echoed so a caller chaining tools can carry it."""

    execution_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="park_execution",
        description=(
            "Record that a walk stopped at a step whose work was handed off and is still "
            "running elsewhere. The execution waits until that work is reported stopped, "
            "and is then claimed again to continue from the step after it."
        ),
    )
    async def park_execution_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        execution_id: UUID,
        occurred_at: datetime | None = None,
    ) -> ParkExecutionOutput:
        handler = get_handler()
        await handler(
            ParkExecution(execution_id=execution_id, occurred_at=occurred_at),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ParkExecutionOutput(execution_id=execution_id)
