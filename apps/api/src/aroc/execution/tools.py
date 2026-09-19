"""Register the Execution MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from aroc.execution.features.define_plan import tool as define_plan_tool
from aroc.execution.features.get_plan import tool as get_plan_tool
from aroc.execution.wire import ExecutionHandlers


def register_execution_tools(
    mcp: FastMCP,
    *,
    get_handlers: Callable[[], ExecutionHandlers],
) -> None:
    """Register every Execution slice's MCP tool."""
    define_plan_tool.register(
        mcp,
        get_handler=lambda: get_handlers().define_plan,
    )
    get_plan_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_plan,
    )


__all__ = ["register_execution_tools"]
