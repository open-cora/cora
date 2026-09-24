"""Events the Procedure aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits
them, because they are facts about the aggregate's history. A slice
decides when one happens; the history is not the slice's to own.

One member today. The alias below is still written out, and the evolver
still closes over it with `assert_never`, because the second member is
what those two guards exist for and adding them later means adding them
under pressure.

## Why the steps are typed and not left a list of dicts

The rule in docs/reference/modeling.md is primitives on events, and its
narrower carve-out is what applies here: a `dict`-typed field is opaque
as a whole, so a carrier mixing closed leaves with open ones loses the
closed ones too. A step list is exactly that mix. An acquisition's
`plan_id` is a reference to a sibling stream and its `parameters` are
freeform, and flattening the list to `list[dict[str, Any]]` would make
the reference as unreadable as the freeform half.

So the event declares the step union and the two functions below are
where it becomes and stops being a payload. That is the same treatment
`PolicyDefined` gives a set of permissions, and for the same reason.

The `kind` key is the discriminator on the wire. It is not a field on
either step class, because in the model the class IS the kind and a
field saying so again is a second thing to get wrong.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from aroc.execution.aggregates.procedure.state import (
    AcquireStep,
    MoveStep,
    ProcedureStep,
)
from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.infrastructure.slices.payload import deserialize_or_raise

_MOVE_KIND = "move"
_ACQUIRE_KIND = "acquire"


@dataclass(frozen=True)
class ProcedureDefined:
    """A routine was composed here, in this order, over these devices.

    Defined rather than registered, the way a plan is: nothing anywhere
    holds this sequence until this event says so, and the record IS the
    procedure.

    `procedure_name`, not `name`. Qualified because the personal-data
    check reads field names and cannot tell a routine's name from a
    person's; an unqualified `name` on an append-only row is the shape
    that rule exists to stop. The state keeps the bare `name`, where the
    aggregate it hangs off already supplies the qualifier.

    The whole step list rides the genesis, and nothing edits it
    afterwards. A procedure changed after something walked it would make
    that walk's record a record of the wrong thing, so a change is a new
    procedure and the old one stays readable.
    """

    procedure_id: UUID
    procedure_name: str
    steps: tuple[ProcedureStep, ...]
    occurred_at: datetime


ProcedureEvent = ProcedureDefined
"""Every event that can appear on a Procedure stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def _step_to_payload(step: ProcedureStep) -> dict[str, Any]:
    """Render one step as the primitives that get stored."""
    match step:
        case MoveStep():
            return {"kind": _MOVE_KIND, "record": step.record, "to": step.to}
        case AcquireStep():
            return {
                "kind": _ACQUIRE_KIND,
                "plan_id": str(step.plan_id),
                "parameters": step.parameters,
                "scopes": list(step.scopes),
            }
        case _:
            assert_never(step)


def _step_from_payload(raw: dict[str, Any]) -> ProcedureStep:
    """Rebuild one step from its stored form.

    Raises `ValueError` on a kind this version does not know, which the
    caller turns into a deserialization failure naming the event. A row
    written by a later version reaching an earlier one is the case that
    produces it, and failing to load is the honest answer: a procedure
    folded with one of its steps silently dropped would be a different
    routine wearing the same id.
    """
    match raw.get("kind"):
        case "move":
            return MoveStep(record=raw["record"], to=float(raw["to"]))
        case "acquire":
            return AcquireStep(
                plan_id=UUID(raw["plan_id"]),
                parameters=dict(raw["parameters"]),
                scopes=tuple(raw["scopes"]),
            )
        case unknown:
            msg = f"Unknown Procedure step kind: {unknown!r}"
            raise ValueError(msg)


def to_payload(event: ProcedureEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case ProcedureDefined():
            return {
                "procedure_id": str(event.procedure_id),
                "procedure_name": event.procedure_name,
                "steps": [_step_to_payload(step) for step in event.steps],
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> ProcedureEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because several constructors in the arm
    below raise it on malformed input: a string that is not a UUID, a
    string that is not a timestamp, and a step kind this version does not
    know. Without it those escape as themselves, naming the field rather
    than the event.

    The parameters come back as whatever the row holds, with no check
    against the plan's schema as it stands today. They were checked when
    they were written and the row cannot have changed since; re-checking
    here would mean a plan that later grew stricter could stop an old
    procedure from loading at all.
    """
    payload = stored.payload
    match stored.event_type:
        case "ProcedureDefined":
            return deserialize_or_raise(
                "ProcedureDefined",
                lambda: ProcedureDefined(
                    procedure_id=UUID(payload["procedure_id"]),
                    procedure_name=payload["procedure_name"],
                    steps=tuple(_step_from_payload(raw) for raw in payload["steps"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Procedure event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = ["ProcedureDefined", "ProcedureEvent", "from_stored", "to_payload"]
