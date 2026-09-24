"""Events the Walk aggregate emits, and the union its evolver dispatches on.

## The genesis is a dispatch, and that is a claim about who acted

`WalkDispatched` says this system handed a procedure out to be driven.
It is not `WalkReported`, and the difference is the whole posture: a
reported record says somebody else did something and told this system
afterwards, and a dispatched one says this system asked.

That distinction is carried by the class and not by a field, which is
the rule docs/bounded-contexts/execution.md draws for a run and applies
here unchanged. Which class opened a stream is what says who drove the
act, and a field saying so could be set wrong.

`WalkClaimed` is the only event here that neither this system nor a step
produces. Something driving says it has taken the walk up, which is what
turns a dispatch that may be sitting unread into one that is being
acted on. Who claimed it is on the envelope, as the principal that
issued the command, so no field repeats it.

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

from aroc.execution.aggregates.walk.state import DispatchedStep
from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class WalkDispatched:
    """A procedure was handed out to be driven.

    Cites the procedure and copies its name and its steps. The copy is
    not redundancy: the fold is pure and cannot load another stream, so
    the length of the step list has to be here for the outcomes to have
    anywhere to land.

    Carrying the whole list up front is also what makes the record
    readable after the thing driving it has gone. Steps are reported one
    at a time, so without the list a reader of a walk that stopped
    reporting would be looking at a prefix, with no way to tell a walk
    that finished early from one that was abandoned.
    """

    walk_id: UUID
    procedure_id: UUID
    procedure_name: str
    steps: list[DispatchedStep]
    occurred_at: datetime


@dataclass(frozen=True)
class WalkClaimed:
    """Something driving said it has taken this walk up.

    No field naming what claimed it. The envelope carries the principal
    that issued the command, and a deployment runs one service account
    per beamline, so the answer is already on the row and a second copy
    could disagree with it.
    """

    walk_id: UUID
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

    Which step held the device and which scopes collided are not carried.
    They belong to a ledger in the driver's process, and the argument for
    leaving them there is in `state.py`.
    """

    walk_id: UUID
    index: int
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


@dataclass(frozen=True)
class WalkStepRunStarted:
    """The engine opened the run an acquisition step asked for.

    The genesis of the second account of one step. Six classes rather
    than one carrying a state, for the reason the four outcome classes
    exist: a field can be set wrong and a class cannot, and these are
    rows nobody can go back and fix.

    `engine_reference` is what the engine calls this run. It arrives here
    as well as on `WalkStepDone` because the two reach this system from
    different clients on different schedules, and whichever lands first
    is the one that lets anybody find the run.
    """

    walk_id: UUID
    step_id: UUID
    engine_reference: str | None
    occurred_at: datetime


@dataclass(frozen=True)
class WalkStepRunPaused:
    """The engine stopped where it was and can carry on."""

    walk_id: UUID
    step_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class WalkStepRunResumed:
    """The engine carried on from where it paused.

    The only edge on this machine that points backwards, which is what
    makes a step's engine state non-monotonic while its stream still only
    grows. A run's is the same and for the same reason.
    """

    walk_id: UUID
    step_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class WalkStepRunCompleted:
    """The engine reached its own end.

    Says the engine reported success, and nothing about whether the
    science worked. Every corrupted scan in `spikes/conductor/FINDINGS.md`
    ended this way.
    """

    walk_id: UUID
    step_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class WalkStepRunAborted:
    """Something outside the run stopped it."""

    walk_id: UUID
    step_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class WalkStepRunFailed:
    """The run broke.

    Carries no reason, for the reason `WalkStepBroken` carries a class
    name and not a message: an engine's failure text is free text of
    unknown provenance heading for a row nobody can edit.
    """

    walk_id: UUID
    step_id: UUID
    occurred_at: datetime


WalkEvent = (
    WalkDispatched
    | WalkClaimed
    | WalkStepDone
    | WalkStepRefused
    | WalkStepBroken
    | WalkStepSkipped
    | WalkStepRunStarted
    | WalkStepRunPaused
    | WalkStepRunResumed
    | WalkStepRunCompleted
    | WalkStepRunAborted
    | WalkStepRunFailed
    | WalkEnded
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
        case WalkDispatched():
            return {
                "walk_id": str(event.walk_id),
                "procedure_id": str(event.procedure_id),
                "procedure_name": event.procedure_name,
                "steps": [
                    {"id": str(step.id), "describes": step.describes} for step in event.steps
                ],
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkClaimed():
            return {
                "walk_id": str(event.walk_id),
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
        case WalkStepRunStarted():
            return {
                "walk_id": str(event.walk_id),
                "step_id": str(event.step_id),
                "engine_reference": event.engine_reference,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkStepRunPaused():
            return {
                "walk_id": str(event.walk_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkStepRunResumed():
            return {
                "walk_id": str(event.walk_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkStepRunCompleted():
            return {
                "walk_id": str(event.walk_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkStepRunAborted():
            return {
                "walk_id": str(event.walk_id),
                "step_id": str(event.step_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case WalkStepRunFailed():
            return {
                "walk_id": str(event.walk_id),
                "step_id": str(event.step_id),
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
        case "WalkDispatched":
            return deserialize_or_raise(
                "WalkDispatched",
                lambda: WalkDispatched(
                    walk_id=UUID(payload["walk_id"]),
                    procedure_id=UUID(payload["procedure_id"]),
                    procedure_name=payload["procedure_name"],
                    steps=[
                        DispatchedStep(id=UUID(raw["id"]), describes=raw["describes"])
                        for raw in payload["steps"]
                    ],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkClaimed":
            return deserialize_or_raise(
                "WalkClaimed",
                lambda: WalkClaimed(
                    walk_id=UUID(payload["walk_id"]),
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
        case "WalkStepRunStarted":
            return deserialize_or_raise(
                "WalkStepRunStarted",
                lambda: WalkStepRunStarted(
                    walk_id=UUID(payload["walk_id"]),
                    step_id=UUID(payload["step_id"]),
                    engine_reference=payload["engine_reference"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkStepRunPaused":
            return deserialize_or_raise(
                "WalkStepRunPaused",
                lambda: WalkStepRunPaused(
                    walk_id=UUID(payload["walk_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkStepRunResumed":
            return deserialize_or_raise(
                "WalkStepRunResumed",
                lambda: WalkStepRunResumed(
                    walk_id=UUID(payload["walk_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkStepRunCompleted":
            return deserialize_or_raise(
                "WalkStepRunCompleted",
                lambda: WalkStepRunCompleted(
                    walk_id=UUID(payload["walk_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkStepRunAborted":
            return deserialize_or_raise(
                "WalkStepRunAborted",
                lambda: WalkStepRunAborted(
                    walk_id=UUID(payload["walk_id"]),
                    step_id=UUID(payload["step_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "WalkStepRunFailed":
            return deserialize_or_raise(
                "WalkStepRunFailed",
                lambda: WalkStepRunFailed(
                    walk_id=UUID(payload["walk_id"]),
                    step_id=UUID(payload["step_id"]),
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
    "WalkClaimed",
    "WalkDispatched",
    "WalkEnded",
    "WalkEvent",
    "WalkStepBroken",
    "WalkStepDone",
    "WalkStepRefused",
    "WalkStepRunAborted",
    "WalkStepRunCompleted",
    "WalkStepRunFailed",
    "WalkStepRunPaused",
    "WalkStepRunResumed",
    "WalkStepRunStarted",
    "WalkStepSkipped",
    "from_stored",
    "to_payload",
]
