"""MCP door for reporting a run.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

The reference pair arrives as two flat arguments here, where the route
takes a nested object. A tool's arguments are a flat keyword list, and
nesting one object inside it would buy shape at the cost of every client
having to construct it. Both doors build the same value object before
the command exists, which is where the shape actually matters.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from aroc.execution.features.report_run.command import ReportRun
from aroc.execution.features.report_run.handler import IdempotentHandler
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id
from aroc.shared.identifier import Identifier


class ReportRunOutput(BaseModel):
    """What the tool hands back."""

    run_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="report_run",
        description=(
            "Record that an external engine ran a plan: the plan id, the "
            "parameters it was given, and the engine's own id for the run."
        ),
    )
    async def report_run_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        plan_id: UUID,
        parameters: dict[str, Any],
        external_ref_scheme: str,
        external_ref_value: str,
    ) -> ReportRunOutput:
        handler = get_handler()
        run_id = await handler(
            ReportRun(
                plan_id=plan_id,
                parameters=parameters,
                external_ref=Identifier(scheme=external_ref_scheme, value=external_ref_value),
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ReportRunOutput(run_id=run_id)
