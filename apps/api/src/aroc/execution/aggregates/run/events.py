"""Events the Run aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits
them, because they are facts about the aggregate's history. A slice
decides when one happens; the history is not the slice's to own.

## One genesis event per way a run can come to be known

`RunReported` says an engine ran something and this system was told
about it afterwards. It derives from `ReportRun` the way the naming rule
requires, which is what settled a question worth writing down, because
the first draft of this module got it the other way round.

That draft had one genesis event for both ways a run can arrive, with a
field naming which one it was, and the conducting path was going to add
that field later. Derivability rules it out: two differently named
commands cannot both derive one event name. So conducting gets its own
genesis event instead, and the way a run came to be known is carried by
which class the stream opens with.

That is the better shape, and not only because a rule says so. A field
can be set wrong, which is why the project this chassis came from needed
a structural test forbidding a reported genesis from claiming it had
conducted the act. Two classes cannot be set wrong. The distinction stops
being something to check and becomes something there is no way to write,
which is the same move the policy aggregate makes by holding pairs
instead of two lists.

## The external reference travels as two strings

`Identifier` is a value object and events carry primitives, so the pair
is flattened into `external_ref_scheme` and `external_ref_value` here and
rebuilt by the fold. The closed-vocabulary carve-out in
docs/reference/modeling.md does not apply: an identifier scheme is open
by construction, which is the whole point of that value object.

`parameters` rides the payload as the JSON document it already is, with
the same shallow copy on fold that the plan's schema gets, for the same
reason: a dict field cannot be made immutable at the type level.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class RunReported:
    """An engine ran a plan, and this system was told so.

    Says nothing about how the run ended, or whether it did, and nothing
    about whether the report is true. What is recorded is that the claim
    was made, by the principal the envelope names. This event opens a
    stream whose later members do not exist yet.
    """

    run_id: UUID
    plan_id: UUID
    parameters: dict[str, Any]
    external_ref_scheme: str
    external_ref_value: str
    occurred_at: datetime


RunEvent = RunReported
"""Every event that can appear on a Run stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: RunEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case RunReported():
            return {
                "run_id": str(event.run_id),
                "plan_id": str(event.plan_id),
                "parameters": event.parameters,
                "external_ref_scheme": event.external_ref_scheme,
                "external_ref_value": event.external_ref_value,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> RunEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because three constructors in the arm
    below raise it on malformed input: two strings that are not UUIDs,
    and one that is not a timestamp. Without it those escape as
    themselves, naming the field rather than the event.

    The reference pair comes back as two plain strings and is not
    reassembled into a value object here. That happens in the fold, which
    is where the re-validation belongs: this function's job is to turn a
    row back into the event that was written, and the event was written
    with strings.
    """
    payload = stored.payload
    match stored.event_type:
        case "RunReported":
            return deserialize_or_raise(
                "RunReported",
                lambda: RunReported(
                    run_id=UUID(payload["run_id"]),
                    plan_id=UUID(payload["plan_id"]),
                    parameters=payload["parameters"],
                    external_ref_scheme=payload["external_ref_scheme"],
                    external_ref_value=payload["external_ref_value"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Run event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = ["RunEvent", "RunReported", "from_stored", "to_payload"]
