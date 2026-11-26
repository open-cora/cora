"""MCP door for retiring a procedure.

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

from keeper.execution.features.retire_procedure.command import RetireProcedure
from keeper.execution.features.retire_procedure.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class RetireProcedureOutput(BaseModel):
    """What the tool hands back.

    The id it was given, because a tool result of nothing reads as a
    failure to a caller that cannot see a 204.
    """

    procedure_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="retire_procedure",
        description=(
            "Stop handing a procedure out, because nothing will drive it any longer. "
            "From then on a dispatch of it is refused. Its steps and every execution "
            "of it stay readable, and executions already dispatched are not touched. "
            "Refused if the procedure is already retired, or if the caller may not "
            "retire procedures at the beamline it runs at."
        ),
    )
    async def retire_procedure_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        procedure_id: UUID,
    ) -> RetireProcedureOutput:
        handler = get_handler()
        await handler(
            RetireProcedure(procedure_id=procedure_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RetireProcedureOutput(procedure_id=procedure_id)
