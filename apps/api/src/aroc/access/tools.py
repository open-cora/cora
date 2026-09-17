"""Register the Access MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from aroc.access.features.deactivate_actor import tool as deactivate_actor_tool
from aroc.access.features.register_actor import tool as register_actor_tool
from aroc.access.wire import AccessHandlers


def register_access_tools(
    mcp: FastMCP,
    *,
    get_handlers: Callable[[], AccessHandlers],
) -> None:
    """Register every Access slice's MCP tool."""
    register_actor_tool.register(
        mcp,
        get_handler=lambda: get_handlers().register_actor,
    )
    deactivate_actor_tool.register(
        mcp,
        get_handler=lambda: get_handlers().deactivate_actor,
    )


__all__ = ["register_access_tools"]
