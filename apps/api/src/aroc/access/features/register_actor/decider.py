"""The decision: what registering an actor produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent, which is
what makes the same inputs give the same events on replay.
"""

from datetime import datetime
from uuid import UUID

from aroc.access.aggregates.actor import Actor, ActorAlreadyExistsError, ActorName, ActorRegistered
from aroc.access.features.register_actor.command import RegisterActor


def decide(
    state: Actor | None,
    command: RegisterActor,
    *,
    now: datetime,
    new_id: UUID,
) -> list[ActorRegistered]:
    """Decide the events produced by registering an actor.

    Invariants:
      - State must be None, or the id already has a history
        -> ActorAlreadyExistsError
      - Name must be non-empty after trimming and within the bound
        -> InvalidActorNameError

    The name is validated here and then dropped. That looks wasteful and
    is the point: the check belongs with the decision, so a bad name is
    refused before the handler touches any store, while the value itself
    must not reach the event. The handler validates again on its way to
    the profile table, which is the only place the trimmed value is kept.
    """
    if state is not None:
        raise ActorAlreadyExistsError(state.id)
    ActorName(command.name)
    return [ActorRegistered(actor_id=new_id, occurred_at=now)]


__all__ = ["decide"]
