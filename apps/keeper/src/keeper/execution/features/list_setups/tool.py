"""MCP door for listing setups.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The description says that a row carries no settings, because a model that
does not know will read a listing and report that a setup holds nothing.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.features.list_setups.handler import Handler
from keeper.execution.features.list_setups.query import DEFAULT_PAGE_SIZE, ListSetups
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class SetupSummaryOutput(BaseModel):
    """One setup, as a list shows it.

    No settings and no settings schema: a page of them is mostly documents, and
    `get_setup` has both.
    """

    setup_id: UUID
    beamline: str
    operation_id: UUID
    name: str
    revision: int
    created_at: datetime
    revised_at: datetime


class ListSetupsOutput(BaseModel):
    """A page of setups, and how to ask for the next one."""

    items: list[SetupSummaryOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_setups",
        description=(
            "List setups, newest first. Give a beamline to see the setups one station "
            "holds, an operation to see the setups that serve it, a name, or any of "
            "those together; all three together are the key one setup holds. A row says "
            "which revision a setup is at and when it was made, and carries no settings; "
            "read those with get_setup. Pass the next_cursor from a response to read the "
            "next page."
        ),
    )
    async def list_setups_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        beamline: str | None = None,
        operation_id: UUID | None = None,
        name: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListSetupsOutput:
        handler = get_handler()
        page = await handler(
            ListSetups.from_filters(
                beamline=beamline,
                operation_id=operation_id,
                name=name,
                limit=limit,
                cursor=cursor,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListSetupsOutput(
            items=[
                SetupSummaryOutput(
                    setup_id=summary.setup_id,
                    beamline=summary.beamline.value,
                    operation_id=summary.operation_id,
                    name=summary.name.value,
                    revision=summary.revision,
                    created_at=summary.created_at,
                    revised_at=summary.revised_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
