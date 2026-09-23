"""Events the Walk aggregate emits, and the union its evolver dispatches on.

## One genesis event per way a walk can come to be known

`WalkReported` says something drove a procedure and told this system
what it did. It derives from `ReportWalk` the way the naming rule
requires, and it is deliberately the same word the Run aggregate uses
for the same posture: told, not observed.

The driving genesis is reserved and not here. When this system asks for
a walk rather than being told about one, that arrives as its own class
on this same stream, the way a driving verb is reserved beside every
reporting one in docs/bounded-contexts/execution.md. Which class opened
a stream is what says who drove the act, and a field saying so could be
set wrong.

## Four events for four outcomes, rather than one with a word on it

A step's outcome could have ridden on a single step event as a string.
It does not, for the reason the Run aggregate derives its status from
the event type: a field can be set wrong and a class cannot, and this is
an append-only row nobody can go back and fix.

It also removes four nullable fields. Each class carries what its own
outcome has and nothing else: a reference to the run that was opened, or
who was holding the device, or what the seam raised. A skipped step
carries neither, which is the whole of what skipped means.

The slice that emits these is therefore out of scope for the
command-to-event derivation check, which covers slices emitting exactly
one event. `ReportWalkStep` picks among four by what the caller
reported.

## What a broken step carries

`cause` is the class name of whatever the seam raised, never its
message. The state module gives the argument: a driver's message is free
text of unknown provenance heading for a row nobody can edit, and the
class name is what separates a motor that would not move from a typo in
an adapter.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class WalkReported:
    """Something drove a procedure, and this system was told so.

    Carries the whole step list, which is what makes the record readable
    after the thing driving it has gone. A driver reports steps one at a
    time, so without the list up front a reader of a walk that stopped
    reporting would be looking at a prefix, with no way to tell a walk
    that finished early from one that was abandoned.
    """

    walk_id: UUID
    reference_scheme: str
    reference_value: str
    procedure_name: str
    steps: list[str]
    occurred_at: datetime


@dataclass(frozen=True)
class WalkStepDone:
    """A step's seam returned without raising.

    Says nothing about whether the step did what it meant to. Every
    corrupted scan measured in `spikes/conductor/FINDINGS.md` came back
    reporting success, so this is a claim this system was given rather
    than a fact it checked, and a word here meaning more would launder
    the one into the other.

    `engine_reference` is what the engine calls the run this step opened,
    for an acquisition step that opened one. None for a move, which opens
    nothing, and None for an acquisition whose engine had no name to
    give.
    """

    walk_id: UUID
    index: int
    engine_reference: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class WalkStepRefused:
    """A claim conflict stopped a step before it touched anything.

    The only outcome in this set that is unambiguously good news:
    whatever was driving did the one thing a claim exists for.

    `holder` names what already had the device and `overlap` names which
    scopes collided. Both are the driver's own vocabulary for its steps
    and the beamline's for its records, neither of which this system
    mints or resolves.
    """

    walk_id: UUID
    index: int
    holder: str
    overlap: list[str]
    occurred_at: datetime


@dataclass(frozen=True)
class WalkStepBroken:
    """A step's seam raised.

    `cause` is the exception's class name and not its message. The
    grammar is the naming rule rather than a preference: an event names
    what happened in the past participle, and the driver's own word for
    this outcome is the past tense of the same verb.
    """

    walk_id: UUID
    index: int
    cause: str
    occurred_at: datetime


@dataclass(frozen=True)
class WalkStepSkipped:
    """The walk had already stopped before reaching this step.

    Recorded rather than left out, so a reader sees the whole procedure
    and where it stopped. A step missing from the record and a step that
    was never reached would otherwise look identical, and only one of
    them means the driver is still alive.
    """

    walk_id: UUID
    index: int
    occurred_at: datetime


@dataclass(frozen=True)
class WalkEnded:
    """The walk is over, and nothing further will be reported under it.

    Says nothing about whether it finished, which the steps already say.
    A walk that stopped at its first failure ends exactly like one that
    ran every step, because ending is about the driver having no more to
    report and not about how it went.

    The absence of this event is the load-bearing part. A walk whose
    driver died has a genesis, some steps, and no ending, which is how a
    reader tells it from one still in flight only by waiting. Closing
    that gap needs something that can say the driver is gone, and nothing
    can yet.
    """

    walk_id: UUID
    occurred_at: datetime


WalkEvent = (
    WalkReported | WalkStepDone | WalkStepRefused | WalkStepBroken | WalkStepSkipped | WalkEnded
)
"""Every event that can appear on a Walk stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: WalkEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case WalkReported():
            return {
                "walk_id": str(event.walk_id),
                "reference_scheme": event.reference_scheme,
                "reference_value": event.reference_value,
                "procedure_name": event.procedure_name,
                "steps": list(event.steps),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkStepDone():
            return {
                "walk_id": str(event.walk_id),
                "index": event.index,
                "engine_reference": event.engine_reference,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkStepRefused():
            return {
                "walk_id": str(event.walk_id),
                "index": event.index,
                "holder": event.holder,
                "overlap": list(event.overlap),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkStepBroken():
            return {
                "walk_id": str(event.walk_id),
                "index": event.index,
                "cause": event.cause,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkStepSkipped():
            return {
                "walk_id": str(event.walk_id),
                "index": event.index,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkEnded():
            return {
                "walk_id": str(event.walk_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> WalkEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because the constructors below raise it
    on malformed input: a string that is not a UUID, and one that is not
    a timestamp. Without it those escape as themselves, naming the field
    rather than the event.

    The reference pair comes back as two plain strings and is not
    reassembled into a value object here. That happens in the fold, which
    is where the re-validation belongs: this function turns a row back
    into the event that was written, and the event was written with
    strings.

    The arms are spelled out one per class although two of them differ
    only in which class they build. A shared arm would have to pick the
    class by lookup, and a lookup is where a typo becomes a wrong event
    class rather than a failing branch. A skipped step folded as an
    ending would close a walk that is still running.
    """
    payload = stored.payload
    match stored.event_type:
        case "WalkReported":
            return deserialize_or_raise(
                "WalkReported",
                lambda: WalkReported(
                    walk_id=UUID(payload["walk_id"]),
                    reference_scheme=payload["reference_scheme"],
                    reference_value=payload["reference_value"],
                    procedure_name=payload["procedure_name"],
                    steps=list(payload["steps"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkStepDone":
            return deserialize_or_raise(
                "WalkStepDone",
                lambda: WalkStepDone(
                    walk_id=UUID(payload["walk_id"]),
                    index=payload["index"],
                    engine_reference=payload["engine_reference"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkStepRefused":
            return deserialize_or_raise(
                "WalkStepRefused",
                lambda: WalkStepRefused(
                    walk_id=UUID(payload["walk_id"]),
                    index=payload["index"],
                    holder=payload["holder"],
                    overlap=list(payload["overlap"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkStepBroken":
            return deserialize_or_raise(
                "WalkStepBroken",
                lambda: WalkStepBroken(
                    walk_id=UUID(payload["walk_id"]),
                    index=payload["index"],
                    cause=payload["cause"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkStepSkipped":
            return deserialize_or_raise(
                "WalkStepSkipped",
                lambda: WalkStepSkipped(
                    walk_id=UUID(payload["walk_id"]),
                    index=payload["index"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkEnded":
            return deserialize_or_raise(
                "WalkEnded",
                lambda: WalkEnded(
                    walk_id=UUID(payload["walk_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Walk event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = [
    "WalkEnded",
    "WalkEvent",
    "WalkReported",
    "WalkStepBroken",
    "WalkStepDone",
    "WalkStepRefused",
    "WalkStepSkipped",
    "from_stored",
    "to_payload",
]
