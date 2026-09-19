"""MCP door for reading a run.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from aroc.execution.features.get_run.handler import Handler
from aroc.execution.features.get_run.query import GetRun
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id


class GetRunOutput(BaseModel):
    """A run as this system currently holds it.

    The reference pair is flat here, matching the tool that writes one.
    Both tools keep the shape a flat keyword list gives them, and the
    routes keep the nested object a JSON body gives them.
    """

    run_id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    external_ref_scheme: str
    external_ref_value: str


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_run",
        description="Read a run by id: the plan it ran, its parameters, and the engine's own id.",
    )
    async def get_run_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        run_id: UUID,
    ) -> GetRunOutput:
        handler = get_handler()
        run = await handler(
            GetRun(run_id=run_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetRunOutput(
            run_id=run.id,
            plan_id=run.plan_id,
            parameters=run.parameters,
            external_ref_scheme=run.external_ref.scheme,
            external_ref_value=run.external_ref.value,
        )
