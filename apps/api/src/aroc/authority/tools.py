"""Register the Authority MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from aroc.authority.features.define_policy import tool as define_policy_tool
from aroc.authority.features.grant_permission import tool as grant_permission_tool
from aroc.authority.features.revoke_permission import tool as revoke_permission_tool
from aroc.authority.wire import AuthorityHandlers


def register_authority_tools(
    mcp: FastMCP,
    *,
    get_handlers: Callable[[], AuthorityHandlers],
) -> None:
    """Register every Authority slice's MCP tool."""
    define_policy_tool.register(
        mcp,
        get_handler=lambda: get_handlers().define_policy,
    )
    grant_permission_tool.register(
        mcp,
        get_handler=lambda: get_handlers().grant_permission,
    )
    revoke_permission_tool.register(
        mcp,
        get_handler=lambda: get_handlers().revoke_permission,
    )


__all__ = ["register_authority_tools"]
