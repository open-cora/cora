"""Actor state and its domain errors.

An Actor is a party this system has a record of: a person, a service
account, a background process. The aggregate answers one question,
whether this id names someone the system has been told about.

## Why the state is only an id

A display name is the field a reader expects here, and it is absent on
purpose. The actors this system sees are service accounts, which are
named where they are provisioned rather than here, so a name field
would be shaped now by guesswork and argued with later by its first
real caller.

Its absence is also what keeps personal data out of the record. Events
are immutable and INSERT-only at the database role level, so a name
written into a payload cannot be taken back out. Nothing in this system
holds personal data today, and writing no name is the cheapest way to
keep that true while the question of where a name would live stays open.

Availability, whether an actor is switched on, is absent for a plainer
reason. A flag nothing can change is dead weight, so it arrives with the
command that flips it rather than ahead of it.
"""

from dataclasses import dataclass
from uuid import UUID


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


@dataclass(frozen=True)
class Actor:
    """An actor this system has a record of.

    One field, which is its own id. That is not an oversight: see the
    module docstring for why the rest is absent. The read path returning
    None rather than an `Actor` is the whole of what this aggregate
    currently distinguishes.
    """

    id: UUID


__all__ = [
    "Actor",
    "ActorAlreadyExistsError",
]
