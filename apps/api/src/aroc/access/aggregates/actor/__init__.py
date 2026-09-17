"""The Actor aggregate: state, events, evolver, and its read path."""

from aroc.access.aggregates.actor.events import (
    ActorDeactivated,
    ActorEvent,
    ActorReactivated,
    ActorRegistered,
    from_stored,
    to_payload,
)
from aroc.access.aggregates.actor.evolver import evolve, fold
from aroc.access.aggregates.actor.read import (
    ACTOR_STREAM_TYPE,
    load_actor,
    load_actor_with_version,
)
from aroc.access.aggregates.actor.state import (
    Actor,
    ActorAlreadyExistsError,
    ActorCannotBeDeactivatedError,
    ActorCannotBeReactivatedError,
    ActorNotFoundError,
)

__all__ = [
    "ACTOR_STREAM_TYPE",
    "Actor",
    "ActorAlreadyExistsError",
    "ActorCannotBeDeactivatedError",
    "ActorCannotBeReactivatedError",
    "ActorDeactivated",
    "ActorEvent",
    "ActorNotFoundError",
    "ActorReactivated",
    "ActorRegistered",
    "evolve",
    "fold",
    "from_stored",
    "load_actor",
    "load_actor_with_version",
    "to_payload",
]
