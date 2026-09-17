"""MCP door for registering an actor.

The same handler the HTTP route uses. The handler is fetched per call
rather than at registration, so it sees the bundle the lifespan wired
rather than whatever existed when the server was built.

No idempotency key. MCP has no client-supplied retry tag to carry one,
so the wrapped handler is called with None and behaves as the bare one.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from aroc.access.aggregates.actor import ACTOR_NAME_MAX_LENGTH
from aroc.access.features.register_actor.command import RegisterActor
from aroc.access.features.register_actor.handler import IdempotentHandler
from aroc.infrastructure.observability import current_correlation_id
from aroc.infrastructure.request import get_mcp_surface_id
from aroc.infrastructure.slices.principal import get_mcp_principal_id


class RegisterActorOutput(BaseModel):
    """What the tool hands back."""

    actor_id: UUID


def register(mcp: FastMCP, *, get_handler: Callable[[], IdempotentHandler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="register_actor",
        description="Register a new actor with the given display name.",
    )
    async def register_actor_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        name: Annotated[
            str,
            Field(
                min_length=1,
                max_length=ACTOR_NAME_MAX_LENGTH,
                description="Display name for the new actor.",
            ),
        ],
    ) -> RegisterActorOutput:
        handler = get_handler()
        actor_id = await handler(
            RegisterActor(name=name),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return RegisterActorOutput(actor_id=actor_id)
