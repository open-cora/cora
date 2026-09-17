"""The register_actor slice, re-exported so callers read `register_actor.bind`."""

from aroc.access.features.register_actor.command import RegisterActor
from aroc.access.features.register_actor.decider import decide
from aroc.access.features.register_actor.handler import Handler, IdempotentHandler, bind
from aroc.access.features.register_actor.route import router

__all__ = [
    "Handler",
    "IdempotentHandler",
    "RegisterActor",
    "bind",
    "decide",
    "router",
]
