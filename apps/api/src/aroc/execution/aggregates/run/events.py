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


@dataclass(frozen=True)
class RunCompleted:
    """The run reached its own end.

    Four fields short of its genesis, and every later event on this
    stream is the same two fields. What is running is already on the
    stream; a later event adds when, and which thing happened, and
    nothing else.

    No reason, no summary, no counts. See the state module on why a
    free-text field is the one thing an append-only row should not grow.
    """

    run_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class RunAborted:
    """Something outside the run stopped it before its own end.

    The contrast with `RunFailed` is where the trouble came from, not how
    bad it was. Aborted is a decision somebody or something made; failed
    is the run breaking. An engine that offers both is drawing the same
    line, and collapsing them here would throw away a distinction the
    source already made.
    """

    run_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class RunFailed:
    """The run broke.

    Distinct from aborted, per that event's docstring. Distinct from
    completed too, and worth saying: a run that failed may still have
    produced data, and this event makes no claim either way. What the run
    left behind is not modelled here at all.
    """

    run_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class RunPaused:
    """The run stopped where it was, and can carry on from there.

    The first non-terminal event after the genesis, and the first one
    that does not close a stream. A paused run is still live: it can be
    resumed, and it can be ended by any of the three endings, because an
    engine sitting at a pause is exactly the one somebody aborts.

    Nothing says why it paused or where. A pause raised by a signal, by
    an operator, and by the routine asking for one itself all arrive
    here as the same fact, because the distinction this system can act on
    is stopped versus not, and the rest is the engine's to keep.
    """

    run_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class RunResumed:
    """The run carried on from where it paused.

    The only event on this stream that returns the run to a status it
    already held. That makes the fold non-monotonic in its derived value
    while the stream itself still only grows, which is the property worth
    keeping straight: history is append-only, and a status is a reading
    of history rather than a tally of it.
    """

    run_id: UUID
    occurred_at: datetime


RunEvent = RunReported | RunCompleted | RunAborted | RunFailed | RunPaused | RunResumed
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
        case RunCompleted() | RunAborted() | RunFailed() | RunPaused() | RunResumed():
            return {
                "run_id": str(event.run_id),
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

    The five arms after the genesis are spelled out separately although
    their bodies are identical, because the class each produces is the
    whole difference between them and a shared arm would have to pick one
    by lookup. A lookup is where a typo becomes a wrong event class
    rather than a failing branch, and a wrong class here folds a
    completed run into an aborted one. Same argument the Actor's three
    arms make.

    Five identical bodies is past the point where a table looks tempting.
    It stays spelled out because the cost of the duplication is reading,
    which a reader pays once, and the cost of the table is a silent wrong
    answer on a stored row nobody can go back and fix.
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
        case "RunCompleted":
            return deserialize_or_raise(
                "RunCompleted",
                lambda: RunCompleted(
                    run_id=UUID(payload["run_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "RunAborted":
            return deserialize_or_raise(
                "RunAborted",
                lambda: RunAborted(
                    run_id=UUID(payload["run_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "RunFailed":
            return deserialize_or_raise(
                "RunFailed",
                lambda: RunFailed(
                    run_id=UUID(payload["run_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "RunPaused":
            return deserialize_or_raise(
                "RunPaused",
                lambda: RunPaused(
                    run_id=UUID(payload["run_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "RunResumed":
            return deserialize_or_raise(
                "RunResumed",
                lambda: RunResumed(
                    run_id=UUID(payload["run_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Run event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "RunAborted",
    "RunCompleted",
    "RunEvent",
    "RunFailed",
    "RunPaused",
    "RunReported",
    "RunResumed",
    "from_stored",
    "to_payload",
]
