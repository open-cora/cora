"""MCP door for declaring an operation's device use.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a replayed declaration is refused by the domain in any case, with the
value the first one wrote.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.declare_operation_device_use.command import (
    DeclareOperationDeviceUse,
)
from keeper.execution.features.declare_operation_device_use.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class DeclareOperationDeviceUseOutput(BaseModel):
    """What the tool hands back.

    The operation and the declaration it was given, because a tool result
    of nothing reads as a failure to a caller that cannot see a 204.
    """

    operation_id: UUID
    drives_devices: bool


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="declare_operation_device_use",
        description=(
            "Declare, once, whether a run of an operation drives devices at the station "
            "that runs it. False is for work that happens somewhere else, such as a "
            "transfer or a reconstruction at another facility: a run of it composed for "
            "a proposal then claims no devices. A run of an operation declared true "
            "claims the devices its adopter or its pursuit names. A plan of several runs "
            "is refused while any operation it cites is undeclared. Refused for a retired "
            "operation, and refused a second time whichever way it points: a wrong "
            "declaration is corrected by defining another operation."
        ),
    )
    async def declare_operation_device_use_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        operation_id: UUID,
        drives_devices: bool,
    ) -> DeclareOperationDeviceUseOutput:
        handler = get_handler()
        await handler(
            DeclareOperationDeviceUse(operation_id=operation_id, drives_devices=drives_devices),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return DeclareOperationDeviceUseOutput(
            operation_id=operation_id, drives_devices=drives_devices
        )
