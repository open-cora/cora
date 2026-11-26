"""MCP door for reading a setup.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.execution.features.get_setup.handler import Handler
from keeper.execution.features.get_setup.query import GetSetup
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class GetSetupOutput(BaseModel):
    """A setup as one revision of it stands."""

    setup_id: UUID
    beamline: str
    operation_id: UUID
    name: str
    revision: int
    settings: dict[str, Any]
    settings_schema: dict[str, Any]


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_setup",
        description=(
            "Read a setup by id: its beamline, the operation it serves, its name, and the "
            "settings and settings schema of its latest revision. Give a revision number "
            "to read "
            "that revision instead; every earlier revision stays readable."
        ),
    )
    async def get_setup_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        setup_id: UUID,
        revision: Annotated[int | None, Field(ge=1)] = None,
    ) -> GetSetupOutput:
        handler = get_handler()
        setup = await handler(
            GetSetup(setup_id=setup_id, revision=revision),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetSetupOutput(
            setup_id=setup.id,
            beamline=setup.beamline.value,
            operation_id=setup.operation_id,
            name=setup.name.value,
            revision=setup.revision,
            settings=setup.settings,
            settings_schema=setup.settings_schema,
        )
