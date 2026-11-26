"""MCP door for revising a setup.

The same handler the HTTP route uses, fetched per call so it sees the
bundle the lifespan wired rather than whatever existed at registration.

No idempotency key. MCP has no client-supplied retry tag to carry one,
and a replayed revision is refused by the domain as made against a
revision that is no longer the latest.
"""

from collections.abc import Callable
from typing import Annotated, Any
from uuid import UUID

from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from keeper.execution.features.revise_setup.command import ReviseSetup
from keeper.execution.features.revise_setup.handler import Handler
from keeper.infrastructure.observability import current_correlation_id
from keeper.infrastructure.request import get_mcp_surface_id
from keeper.infrastructure.slices.principal import get_mcp_principal_id


class ReviseSetupOutput(BaseModel):
    """The setup that was revised, and the number of the revision written."""

    setup_id: UUID
    revision: int


def register(mcp: FastMCP, *, get_handler: Callable[[], Handler]) -> None:
    """Register the tool on the given MCP server."""

    @mcp.tool(
        name="revise_setup",
        description=(
            "Write the next revision of a setup and return its number. Read the setup "
            "with get_setup first and pass the revision it returned as expected_revision; "
            "a revision made against any other than the latest is refused, naming both "
            "numbers, so read again and decide again. Send every setting and the whole "
            "settings schema, not only what changed. Earlier revisions stay readable with "
            "get_setup and a revision number. Also refused if the revision changes "
            "nothing, or if the settings are not exactly the ones the schema describes."
        ),
    )
    async def revise_setup_tool(  # pyright: ignore[reportUnusedFunction]
        ctx: Context[Any, Any, Any],
        setup_id: UUID,
        expected_revision: Annotated[int, Field(ge=1)],
        settings: dict[str, Any],
        settings_schema: dict[str, Any],
    ) -> ReviseSetupOutput:
        handler = get_handler()
        revision = await handler(
            ReviseSetup(
                setup_id=setup_id,
                expected_revision=expected_revision,
                settings=settings,
                settings_schema=settings_schema,
            ),
            principal_id=get_mcp_principal_id(ctx),
            # The tool runs inside the instrumented request that carried
            # it, so the trace context is already in scope.
            correlation_id=current_correlation_id(),
            surface_id=get_mcp_surface_id(),
        )
        return ReviseSetupOutput(setup_id=setup_id, revision=revision)
