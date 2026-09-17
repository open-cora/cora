"""Actor state, its value objects, and its domain errors.

An Actor is a party this system has a record of: a person, a service
account, a background process. The aggregate answers one question,
whether this id names someone the system has been told about.

## Why the state is only an id

Everything else a reader might expect here lives elsewhere, on purpose.

The display name is in the profile side table, never on the aggregate
and never in an event payload. Events are immutable and personal data
has to be erasable, so the two cannot share a home. What survives an
erasure is the id, which every past event still carries and which still
resolves, so the history stays readable with the person removed from it.

`ActorName` is still declared here, because validating the name is part
of what registering an actor means even though the validated value is
written somewhere the stream cannot reach.

Availability, whether an actor is switched on, is deliberately absent.
A flag nothing can change is dead weight, so it arrives with the command
that flips it rather than ahead of it.
"""

from dataclasses import dataclass
from uuid import UUID

from aroc.shared.bounded_text import bounded_name

ACTOR_NAME_MAX_LENGTH = 200
"""Longest display name an actor may carry, after trimming.

Matches the length constraint on the profile table's name column. The two
are written in different languages in different files and nothing checks
that they agree, so changing one means changing the other by hand.
"""


class InvalidActorNameError(ValueError):
    """A display name was empty after trimming, or longer than the bound."""


class ActorAlreadyExistsError(Exception):
    """Registration was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because a registering handler
    mints a fresh id and a fresh id has no history. It exists so that the
    decider states the precondition it relies on rather than assuming it,
    and so a caller that supplies its own id gets a refusal instead of a
    second genesis event on a live stream.
    """

    def __init__(self, actor_id: UUID) -> None:
        super().__init__(f"Actor {actor_id} already exists")
        self.actor_id = actor_id


@bounded_name(max_length=ACTOR_NAME_MAX_LENGTH, error_class=InvalidActorNameError)
@dataclass(frozen=True)
class ActorName:
    """A trimmed, bounded display name for an actor.

    A value object rather than a bare string so the bound is enforced once,
    at construction, rather than at each of the places that will eventually
    accept a name from outside.
    """

    value: str


@dataclass(frozen=True)
class Actor:
    """An actor this system has a record of.

    One field, which is its own id. That is not an oversight: see the
    module docstring for where the rest of an actor lives and why. The
    read path returning None rather than an `Actor` is the whole of what
    this aggregate currently distinguishes.
    """

    id: UUID


__all__ = [
    "ACTOR_NAME_MAX_LENGTH",
    "Actor",
    "ActorAlreadyExistsError",
    "ActorName",
    "InvalidActorNameError",
]
