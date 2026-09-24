"""Register the Execution MCP tools on the shared server.

`get_handlers` is called per tool call, not at registration, so a tool
always reaches the bundle the lifespan wired rather than one captured
before startup finished.
"""

from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from aroc.execution.features.abort_run import tool as abort_run_tool
from aroc.execution.features.claim_walk import tool as claim_walk_tool
from aroc.execution.features.complete_run import tool as complete_run_tool
from aroc.execution.features.define_plan import tool as define_plan_tool
from aroc.execution.features.define_procedure import tool as define_procedure_tool
from aroc.execution.features.dispatch_walk import tool as dispatch_walk_tool
from aroc.execution.features.end_walk import tool as end_walk_tool
from aroc.execution.features.fail_run import tool as fail_run_tool
from aroc.execution.features.get_plan import tool as get_plan_tool
from aroc.execution.features.get_procedure import tool as get_procedure_tool
from aroc.execution.features.get_run import tool as get_run_tool
from aroc.execution.features.get_walk import tool as get_walk_tool
from aroc.execution.features.list_plans import tool as list_plans_tool
from aroc.execution.features.list_procedures import tool as list_procedures_tool
from aroc.execution.features.list_runs import tool as list_runs_tool
from aroc.execution.features.list_walks import tool as list_walks_tool
from aroc.execution.features.pause_run import tool as pause_run_tool
from aroc.execution.features.report_run import tool as report_run_tool
from aroc.execution.features.report_step import tool as report_step_tool
from aroc.execution.features.resume_run import tool as resume_run_tool
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
    list_plans_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_plans,
    )
    define_procedure_tool.register(
        mcp,
        get_handler=lambda: get_handlers().define_procedure,
    )
    get_procedure_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_procedure,
    )
    list_procedures_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_procedures,
    )
    report_run_tool.register(
        mcp,
        get_handler=lambda: get_handlers().report_run,
    )
    get_run_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_run,
    )
    list_runs_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_runs,
    )
    complete_run_tool.register(
        mcp,
        get_handler=lambda: get_handlers().complete_run,
    )
    abort_run_tool.register(
        mcp,
        get_handler=lambda: get_handlers().abort_run,
    )
    fail_run_tool.register(
        mcp,
        get_handler=lambda: get_handlers().fail_run,
    )
    pause_run_tool.register(
        mcp,
        get_handler=lambda: get_handlers().pause_run,
    )
    resume_run_tool.register(
        mcp,
        get_handler=lambda: get_handlers().resume_run,
    )
    dispatch_walk_tool.register(
        mcp,
        get_handler=lambda: get_handlers().dispatch_walk,
    )
    claim_walk_tool.register(
        mcp,
        get_handler=lambda: get_handlers().claim_walk,
    )
    report_step_tool.register(
        mcp,
        get_handler=lambda: get_handlers().report_step,
    )
    end_walk_tool.register(
        mcp,
        get_handler=lambda: get_handlers().end_walk,
    )
    get_walk_tool.register(
        mcp,
        get_handler=lambda: get_handlers().get_walk,
    )
    list_walks_tool.register(
        mcp,
        get_handler=lambda: get_handlers().list_walks,
    )


__all__ = ["register_execution_tools"]
