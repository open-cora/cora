"""MCP door for reading one walk.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from aroc.execution.aggregates.walk import StepOutcome
from aroc.execution.features.get_walk.handler import Handler
from aroc.execution.features.get_walk.query import GetWalk
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id


class WalkStepOutput(BaseModel):
    """One step, and whichever detail its outcome carried.

    `outcome` is null for a step nothing has reported yet, which is not
    the same as a step that was skipped.
    """

    describes: str
    outcome: StepOutcome | None
    engine_reference: str | None
    holder: str | None
    overlap: list[str]
    cause: str | None


class GetWalkOutput(BaseModel):
    """A walk as a reader sees it, steps and all."""

    walk_id: UUID
    reference_scheme: str
    reference_value: str
    procedure_name: str
    ended: bool
    steps: list[WalkStepOutput]


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="get_walk",
        description="Read one walk and how each of its steps ended.",
    )
    async def get_walk_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        walk_id: UUID,
    ) -> GetWalkOutput:
        handler = get_handler()
        walk = await handler(
            GetWalk(walk_id=walk_id),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return GetWalkOutput(
            walk_id=walk.id,
            reference_scheme=walk.reference.scheme,
            reference_value=walk.reference.value,
            procedure_name=walk.procedure_name.value,
            ended=walk.ended,
            steps=[
                WalkStepOutput(
                    describes=step.describes,
                    outcome=step.outcome,
                    engine_reference=step.engine_reference,
                    holder=step.holder,
                    overlap=list(step.overlap),
                    cause=step.cause,
                )
                for step in walk.steps
            ],
        )
