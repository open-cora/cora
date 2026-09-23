"""The get_walk slice, re-exported so callers read `.bind`."""

from aroc.execution.features.get_walk.handler import Handler, bind
from aroc.execution.features.get_walk.query import GetWalk
from aroc.execution.features.get_walk.route import router

__all__ = ["GetWalk", "Handler", "bind", "router"]
