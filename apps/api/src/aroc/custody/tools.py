"""Register the Custody MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from aroc.custody.features.get_dataset import tool as get_dataset_tool
from aroc.custody.features.register_dataset import tool as register_dataset_tool
from aroc.custody.wire import CustodyHandlers


def register_custody_tools(
    mcp: FastMCP,
    *,
    get_handlers: Callable[[], CustodyHandlers],
) -> None:
    """Register every Custody slice's MCP tool."""
    register_dataset_tool.register(
        mcp,
        get_handler=lambda: get_handlers().register_dataset,
    )
    get_dataset_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_dataset,
    )


__all__ = ["register_custody_tools"]
