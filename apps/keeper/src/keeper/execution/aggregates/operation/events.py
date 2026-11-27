"""Events the Operation aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits
them, because they are facts about the aggregate's history. A slice
decides when one happens; the history is not the slice's to own.

Three members, a genesis, one declaration and the bookend:

    OperationDefined             this system wrote the routine down
    OperationDeviceUseDeclared   the facility said whether its runs drive devices
    OperationRetired             this system stopped offering it

All three are acts this system performs, so all three take its clock and
none takes a caller's time. That is R8 in docs/reference/naming.md: what an
engine did is reported from somewhere else, and whether this system still
offers a routine, and what it holds a run of it to, is decided here.

`parameters_schema` rides the payload as the JSON document it already is.
It is the one dict-typed field here, and dict fields are the case the
immutable-collection rule in docs/reference/modeling.md deliberately does
not cover: a JSON Schema is freeform by nature. The companion defence is
the shallow copy the evolver makes on fold, so the stored payload and the
folded state cannot end up sharing one mutable object.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class OperationDefined:
    """A runnable routine was written down here.

    Defined rather than registered. The routine the name points at lives
    in the engine and is not this system's to invent, but the
    operation is: nothing anywhere holds this name paired with this schema
    until this event says so, and the record IS the operation. That is the
    split the genesis verbs draw in the glossary.

    `operation_name`, not `name`. Qualified because the personal-data check
    reads field names and cannot tell a routine's name from a person's;
    an unqualified `name` on an append-only row is the shape that rule
    exists to stop, and the qualifier is what says this one is not that.
    The state keeps the bare `name`, where the aggregate it hangs off
    already supplies the qualifier.
    """

    operation_id: UUID
    operation_name: str
    parameters_schema: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class OperationRetired:
    """A routine is no longer offered to be run.

    Retired rather than withdrawn or removed, for the reasons a device's
    retirement gives in the glossary: withdrawing is what a pursuit's
    authorizer does, and removing would claim the routine left the
    engine, which is a different fact at a different moment that this
    system was not present for.

    It carries no reason. Why an engine stopped answering is free text,
    which is where a person's name arrives in a table nothing can edit,
    and who retired it is on the envelope already.
    """

    operation_id: UUID
    occurred_at: datetime


@dataclass(frozen=True)
class OperationDeviceUseDeclared:
    """The facility said whether a run of this routine drives devices here.

    A new event rather than a field on the genesis, which is the rule for
    every fact this log learns late: an operation defined before anybody
    asked the question is still a definition, and a genesis carrying an
    optional answer would be two shapes of one event told apart by what
    their payloads lack.

    Declared rather than derived. Nothing here can look inside a routine
    to see what it touches, which is why a run states its scopes; what
    this adds is the facility's word, once, for every run of the routine,
    so that a run composed for a proposal is not left holding a station's
    equipment for the hours a transfer or a reconstruction takes
    somewhere else.

    Once, and never again. A declaration found to be wrong is not
    corrected by a second one, the way a schema found to be wrong is not
    edited: another operation is defined, so every procedure composed
    under the first declaration still reads as what it was composed under.

    `drives_devices` and not the step's `drives_no_device`. The step's
    field is a claim made against a default of driving; this one has no
    default at all, because an operation nobody has declared is a third
    state rather than either answer.

    No reason, for the reason a retirement carries none, and who declared
    it is on the envelope.
    """

    operation_id: UUID
    drives_devices: bool
    occurred_at: datetime


OperationEvent = OperationDefined | OperationDeviceUseDeclared | OperationRetired
"""Every event that can appear on an Operation stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: OperationEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case OperationDefined():
            return {
                "operation_id": str(event.operation_id),
                "operation_name": event.operation_name,
                "parameters_schema": event.parameters_schema,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case OperationDeviceUseDeclared():
            return {
                "operation_id": str(event.operation_id),
                "drives_devices": event.drives_devices,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case OperationRetired():
            return {
                "operation_id": str(event.operation_id),
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> OperationEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because two constructors in the arm
    below raise it on malformed input: a string that is not a UUID, and a
    string that is not a timestamp. Without it those escape as
    themselves, naming the field rather than the event.

    The schema comes back as whatever the row holds, with no check that
    it is still one this system would accept today. It was checked when
    it was written and the row cannot have changed since; re-checking
    here would mean a document the validator later grew stricter about
    could stop its stream from loading at all.
    """
    payload = stored.payload
    match stored.event_type:
        case "OperationDefined":
            return deserialize_or_raise(
                "OperationDefined",
                lambda: OperationDefined(
                    operation_id=UUID(payload["operation_id"]),
                    operation_name=payload["operation_name"],
                    parameters_schema=payload["parameters_schema"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "OperationDeviceUseDeclared":
            return deserialize_or_raise(
                "OperationDeviceUseDeclared",
                lambda: OperationDeviceUseDeclared(
                    operation_id=UUID(payload["operation_id"]),
                    drives_devices=_declared(payload["drives_devices"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "OperationRetired":
            return deserialize_or_raise(
                "OperationRetired",
                lambda: OperationRetired(
                    operation_id=UUID(payload["operation_id"]),
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Operation event_type: {unknown!r}"
            raise ValueError(msg)


def _declared(raw: object) -> bool:
    """The stored declaration, refused unless it is one of the two booleans.

    `bool()` would turn a stored string into True whatever it said, and a
    declaration read back as the opposite of what was written decides the
    claims of every run composed from then on.
    """
    if not isinstance(raw, bool):
        msg = "drives_devices is not a boolean"
        raise TypeError(msg)
    return raw


__all__ = [
    "OperationDefined",
    "OperationDeviceUseDeclared",
    "OperationEvent",
    "OperationRetired",
    "from_stored",
    "to_payload",
]
