"""MCP door for defining a setup.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.define_setup.command import DefineSetup
from keeper.execution.features.define_setup.handler import IdempotentHandler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class DefineSetupOutput(BaseModel):
    """What the tool hands back."""

    setup_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="define_setup",
        description=(
            "Define a setup: the values a beamline's conductor applies when it runs one "
            "operation, under a name a step's config parameter can carry, and return its "
            "id. The name is lowercase letters, digits and hyphens, and a second setup "
            "under it for that operation at that beamline is refused, naming the first. "
            "The operation must declare both config and override among its parameters. "
            "The settings schema is a JSON Schema object with one typed property per "
            "setting, and the settings must be exactly the ones it describes. A setup is "
            "never edited; change one with revise_setup, which names the revision it was "
            "made against."
        ),
    )
    async def define_setup_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        beamline: str,
        operation_id: UUID,
        name: str,
        settings: dict[str, Any],
        settings_schema: dict[str, Any],
    ) -> DefineSetupOutput:
        handler = get_handler()
        setup_id = await handler(
            DefineSetup(
                beamline=beamline,
                operation_id=operation_id,
                name=name,
                settings=settings,
                settings_schema=settings_schema,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return DefineSetupOutput(setup_id=setup_id)
