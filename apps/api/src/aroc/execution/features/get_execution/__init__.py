"""The get_execution slice, re-exported so callers read `.bind`."""

from aroc.execution.features.get_execution.handler import Handler, bind
from aroc.execution.features.get_execution.query import GetExecution
from aroc.execution.features.get_execution.route import router

__all__ = ["GetExecution", "Handler", "bind", "router"]
