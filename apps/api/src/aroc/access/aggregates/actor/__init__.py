"""The Actor aggregate: state, events, evolver, and its read path."""

from aroc.access.aggregates.actor.events import (
    ActorEvent,
    ActorRegistered,
    from_stored,
    to_payload,
)
from aroc.access.aggregates.actor.evolver import evolve, fold
from aroc.access.aggregates.actor.read import ACTOR_STREAM_TYPE, load_actor
from aroc.access.aggregates.actor.state import Actor, ActorAlreadyExistsError

__all__ = [
    "ACTOR_STREAM_TYPE",
    "Actor",
    "ActorAlreadyExistsError",
    "ActorEvent",
    "ActorRegistered",
    "evolve",
    "fold",
    "from_stored",
    "load_actor",
    "to_payload",
]
