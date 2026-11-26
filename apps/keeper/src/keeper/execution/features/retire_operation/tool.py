"""MCP door for retiring an operation.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a replayed call is refused by the domain in any case.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.retire_operation.command import RetireOperation
from keeper.execution.features.retire_operation.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class RetireOperationOutput(BaseModel):
    """What the tool hands back.

    The id it was given, because a tool result of nothing reads as a
    failure to a caller that cannot see a 204.
    """

    operation_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="retire_operation",
        description=(
            "Stop offering an operation, because nothing answers to it any longer. "
            "From then on no procedure may cite it, no proposal may be made for it, "
            "and no procedure that runs it may be dispatched. The record and its "
            "schema stay readable. Refused if the operation is already retired."
        ),
    )
    async def retire_operation_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        operation_id: UUID,
    ) -> RetireOperationOutput:
        handler = get_handler()
        await handler(
            RetireOperation(operation_id=operation_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RetireOperationOutput(operation_id=operation_id)
