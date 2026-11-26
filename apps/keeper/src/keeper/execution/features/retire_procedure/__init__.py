"""The retire_procedure slice, re-exported so callers read `.bind`."""

from keeper.execution.features.retire_procedure.command import RetireProcedure
from keeper.execution.features.retire_procedure.decider import decide
from keeper.execution.features.retire_procedure.handler import Handler, bind
from keeper.execution.features.retire_procedure.route import router

__all__ = ["Handler", "RetireProcedure", "bind", "decide", "router"]
