"""The define_procedure slice, re-exported so callers read `define_procedure.bind`."""

from aroc.execution.features.define_procedure.command import DefineProcedure
from aroc.execution.features.define_procedure.context import DefineProcedureContext
from aroc.execution.features.define_procedure.decider import decide
from aroc.execution.features.define_procedure.handler import Handler, IdempotentHandler, bind
from aroc.execution.features.define_procedure.route import router

__all__ = [
    "DefineProcedure",
    "DefineProcedureContext",
    "Handler",
    "IdempotentHandler",
    "bind",
    "decide",
    "router",
]
