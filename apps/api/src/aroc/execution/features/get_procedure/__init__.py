"""The get_procedure slice, re-exported so callers read `get_procedure.bind`."""

from aroc.execution.features.get_procedure.handler import Handler, bind
from aroc.execution.features.get_procedure.query import GetProcedure
from aroc.execution.features.get_procedure.route import router

__all__ = [
    "GetProcedure",
    "Handler",
    "bind",
    "router",
]
