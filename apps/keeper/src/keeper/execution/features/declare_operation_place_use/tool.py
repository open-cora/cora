"""MCP door for declaring an operation's place use.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a replayed declaration is refused by the domain in any case, with the
declaration the first one wrote.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from keeper.execution.aggregates.operation import PlaceUse
from keeper.execution.features.declare_operation_place_use.command import (
    DeclareOperationPlaceUse,
)
from keeper.execution.features.declare_operation_place_use.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class DeclareOperationPlaceUseOutput(BaseModel):
    """What the tool hands back.

    The operation and the declaration it was given, because a tool result
    of nothing reads as a failure to a caller that cannot see a 204.
    """

    operation_id: UUID
    place_parameters: list[str]
    compute_place_parameters: list[str]


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="declare_operation_place_use",
        description=(
            "Declare, once, which parameters of a run of an operation name a place: "
            "place_parameters for places a run reads or writes data at, such as both "
            "ends of a move, and compute_place_parameters for where a run processes. "
            "Either may be empty, which says its runs name no place of that kind. A "
            "pursuit refuses a round whose runs name a place it does not authorize, and "
            "refuses a run of an operation nobody has declared this for. Every parameter "
            "named must be one the operation's schema declares as text. Refused for a "
            "retired operation, and refused a second time: a wrong declaration is "
            "corrected by defining another operation."
        ),
    )
    async def declare_operation_place_use_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        operation_id: UUID,
        place_parameters: list[str],
        compute_place_parameters: list[str],
    ) -> DeclareOperationPlaceUseOutput:
        handler = get_handler()
        await handler(
            DeclareOperationPlaceUse(
                operation_id=operation_id,
                place_use=PlaceUse(
                    place_parameters=tuple(place_parameters),
                    compute_place_parameters=tuple(compute_place_parameters),
                ),
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return DeclareOperationPlaceUseOutput(
            operation_id=operation_id,
            place_parameters=list(place_parameters),
            compute_place_parameters=list(compute_place_parameters),
        )
