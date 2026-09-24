"""The dispatch_execution slice, re-exported so callers read `.bind`."""

from aroc.execution.features.dispatch_execution.command import DispatchExecution
from aroc.execution.features.dispatch_execution.context import DispatchExecutionContext
from aroc.execution.features.dispatch_execution.decider import decide
from aroc.execution.features.dispatch_execution.handler import (
    Handler,
    IdempotentHandler,
    bind,
)
from aroc.execution.features.dispatch_execution.route import router

__all__ = [
    "DispatchExecution",
    "DispatchExecutionContext",
    "Handler",
    "IdempotentHandler",
    "bind",
    "decide",
    "router",
]
