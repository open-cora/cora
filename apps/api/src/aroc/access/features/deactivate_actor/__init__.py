"""The deactivate_actor slice, re-exported so callers read `deactivate_actor.bind`."""

from aroc.access.features.deactivate_actor.command import DeactivateActor
from aroc.access.features.deactivate_actor.decider import decide
from aroc.access.features.deactivate_actor.handler import Handler, bind
from aroc.access.features.deactivate_actor.route import router

__all__ = [
    "DeactivateActor",
    "Handler",
    "bind",
    "decide",
    "router",
]
