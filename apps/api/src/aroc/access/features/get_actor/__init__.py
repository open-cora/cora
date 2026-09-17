"""The get_actor slice, re-exported so callers read `get_actor.bind`."""

from aroc.access.features.get_actor.handler import Handler, bind
from aroc.access.features.get_actor.query import GetActor
from aroc.access.features.get_actor.route import router

__all__ = [
    "GetActor",
    "Handler",
    "bind",
    "router",
]
