"""The end_execution slice, re-exported so callers read `.bind`."""

from aroc.execution.features.end_execution.command import EndExecution
from aroc.execution.features.end_execution.decider import decide
from aroc.execution.features.end_execution.handler import Handler, bind
from aroc.execution.features.end_execution.route import router

__all__ = ["EndExecution", "Handler", "bind", "decide", "router"]
