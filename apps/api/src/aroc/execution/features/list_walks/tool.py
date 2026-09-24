"""MCP door for listing walks.

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

from aroc.execution.aggregates.walk import WalkStatus
from aroc.execution.features.list_walks.handler import Handler
from aroc.execution.features.list_walks.query import DEFAULT_PAGE_SIZE, ListWalks
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id


class WalkSummaryOutput(BaseModel):
    """A walk as a list shows it, without its steps."""

    walk_id: UUID
    procedure_id: UUID
    procedure_name: str
    step_count: int
    reported_count: int
    status: WalkStatus
    created_at: datetime
    updated_at: datetime


class ListWalksOutput(BaseModel):
    """One page, and the cursor that continues it."""

    items: list[WalkSummaryOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_walks",
        description=(
            "List walks newest first. Give a procedure id to see every walk "
            "dispatched for that routine. A row carries how far each got and "
            "what is happening to it; read the steps with get_walk."
        ),
    )
    async def list_walks_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        procedure_id: UUID | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListWalksOutput:
        handler = get_handler()
        page = await handler(
            ListWalks(procedure_id=procedure_id, limit=limit, cursor=cursor),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListWalksOutput(
            items=[
                WalkSummaryOutput(
                    walk_id=summary.walk_id,
                    procedure_id=summary.procedure_id,
                    procedure_name=summary.procedure_name,
                    step_count=summary.step_count,
                    reported_count=summary.reported_count,
                    status=summary.status,
                    created_at=summary.created_at,
                    updated_at=summary.updated_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
