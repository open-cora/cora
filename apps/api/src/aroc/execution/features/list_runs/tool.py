"""MCP door for listing runs.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

The description matters more here than on most tools. A model holding an
engine's identifier for a run has no way to guess that this is where one
gets turned into a run id, so the description says it in the words a
caller would use.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from aroc.execution.aggregates.run import RunStatus
from aroc.execution.features.list_runs.handler import Handler
from aroc.execution.features.list_runs.query import DEFAULT_PAGE_SIZE, ListRuns
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id


class RunSummaryOutput(BaseModel):
    """One run, as a list shows it.

    The reference pair is flat here, matching the other tools. No
    parameters: a page of them is mostly noise to a reader that wanted to
    find a run, and `get_run` has them.
    """

    run_id: UUID
    plan_id: UUID
    external_ref_scheme: str
    external_ref_value: str
    status: RunStatus
    created_at: datetime
    updated_at: datetime


class ListRunsOutput(BaseModel):
    """A page of runs, and how to ask for the next one."""

    items: list[RunSummaryOutput]
    next_cursor: str | None


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="list_runs",
        description=(
            "List runs, newest first. Give both halves of an external reference to "
            "find the run an engine knows by its own id, or give neither to see "
            "recent runs. Pass the next_cursor from a response to read the next page."
        ),
    )
    async def list_runs_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        external_ref_scheme: str | None = None,
        external_ref_value: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> ListRunsOutput:
        handler = get_handler()
        page = await handler(
            ListRuns.with_external_ref(
                scheme=external_ref_scheme,
                value=external_ref_value,
                limit=limit,
                cursor=cursor,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ListRunsOutput(
            items=[
                RunSummaryOutput(
                    run_id=summary.run_id,
                    plan_id=summary.plan_id,
                    external_ref_scheme=summary.external_ref.scheme,
                    external_ref_value=summary.external_ref.value,
                    status=summary.status,
                    created_at=summary.created_at,
                    updated_at=summary.updated_at,
                )
                for summary in page.items
            ],
            next_cursor=page.next_cursor,
        )
