"""MCP door for reporting a walk.

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

from aroc.execution.features.report_walk.command import ReportWalk
from aroc.execution.features.report_walk.handler import IdempotentHandler
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id
from aroc.shared.identifier import Identifier


class ReportWalkOutput(BaseModel):
    """The id this system minted for the walk.

    A caller needs it for every step it reports afterwards, which is the
    one thing this tool hands back that the caller could not have known.
    """

    walk_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="report_walk",
        description="Record that something began walking a procedure, over these steps.",
    )
    async def report_walk_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        reference_scheme: str,
        reference_value: str,
        procedure_name: str,
        steps: list[str],
        occurred_at: datetime | None = None,
    ) -> ReportWalkOutput:
        handler = get_handler()
        walk_id = await handler(
            ReportWalk(
                reference=Identifier(scheme=reference_scheme, value=reference_value),
                procedure_name=procedure_name,
                steps=tuple(steps),
                occurred_at=occurred_at,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ReportWalkOutput(walk_id=walk_id)
