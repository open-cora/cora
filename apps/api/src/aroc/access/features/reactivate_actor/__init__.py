"""The reactivate_actor slice, re-exported so callers read `reactivate_actor.bind`."""

from aroc.access.features.reactivate_actor.command import ReactivateActor
from aroc.access.features.reactivate_actor.decider import decide
from aroc.access.features.reactivate_actor.handler import Handler, bind
from aroc.access.features.reactivate_actor.route import router

__all__ = [
    "Handler",
    "ReactivateActor",
    "bind",
    "decide",
    "router",
]
