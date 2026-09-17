"""Events the Actor aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits them,
because they are facts about the aggregate's history. A slice decides when
one happens; the history is not the slice's to own.

`to_payload` and `from_stored` are the single home for turning an event
into stored primitives and back. A payload carries no personal data, only
ids and timestamps, which is what lets the stream stay immutable while the
profile table stays erasable.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class ActorRegistered:
    """An actor was added to the system's records.

    Carries the id and when it happened, and nothing about the person. The
    display name supplied with the registering command goes to the profile
    table in the same transaction, never into this payload.
    """

    actor_id: UUID
    occurred_at: datetime


ActorEvent = ActorRegistered
"""Every event that can appear on an Actor stream.

One member today. A second arrives as a new class added here and to this
alias, never as a field bolted onto an event already in the log.
"""


def to_payload(event: ActorEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case ActorRegistered():
            return {
                "actor_id": str(event.actor_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> ActorEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because both constructors in the arm below
    raise it on malformed input: a string that is not a UUID, and a string
    that is not a timestamp. Without it those two escape as themselves,
    naming the field rather than the event.
    """
    payload = stored.payload
    match stored.event_type:
        case "ActorRegistered":
            return deserialize_or_raise(
                "ActorRegistered",
                lambda: ActorRegistered(
                    actor_id=UUID(payload["actor_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Actor event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "ActorEvent",
    "ActorRegistered",
    "from_stored",
    "to_payload",
]
