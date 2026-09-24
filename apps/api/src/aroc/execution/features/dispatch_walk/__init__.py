"""The dispatch_walk slice, re-exported so callers read `.bind`."""

from aroc.execution.features.dispatch_walk.command import DispatchWalk
from aroc.execution.features.dispatch_walk.context import DispatchWalkContext
from aroc.execution.features.dispatch_walk.decider import decide
from aroc.execution.features.dispatch_walk.handler import (
    Handler,
    IdempotentHandler,
    bind,
)
from aroc.execution.features.dispatch_walk.route import router

__all__ = [
    "DispatchWalk",
    "DispatchWalkContext",
    "Handler",
    "IdempotentHandler",
    "bind",
    "decide",
    "router",
]
