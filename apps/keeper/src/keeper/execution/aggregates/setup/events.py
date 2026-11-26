"""Events the Setup aggregate emits, and the union its evolver dispatches on.

Events live with the aggregate rather than with the slice that emits
them, because they are facts about the aggregate's history. A slice
decides when one happens; the history is not the slice's to own.

Two members, a genesis and the revision that may follow it any number of
times:

    SetupDefined   this system wrote the values and their schema down
    SetupRevised   this system wrote down the next revision of both

Both are acts this system performs, so both take its clock and neither
takes a caller's time. That is R8 in docs/reference/naming.md.

## A revision carries its number, and the genesis does not

The genesis is revision 1 by definition, so a number on it could only ever
be right by agreeing with the class it sits on. A revision's number is
different: it is what lets a reader of one row say which revision it is
without counting the rows before it, and what lets the summary projection
write an absolute value rather than an increment, which a replayed batch
would apply twice.

## Two dicts, copied on fold

`settings` and `settings_schema` ride the payload as the JSON documents
they already are. Dict fields are the case the immutable-collection rule in
docs/reference/modeling.md deliberately does not cover, and the companion
defence is the shallow copy the evolver makes, so the stored payload and
the folded state never share one mutable object.

Every revision carries both whole. A revision that carried only what
changed would make every reader fold the stream to learn the rest, and a
schema that lost a setting would need a way to say so that a document of
differences does not have.

## A revision does not carry the revision it was made against

It was checked, and it is always the one before the revision the event
carries: the decider refuses any other. So it is derivable from the number
already on the row, and a second number that can only agree with the first
is a second thing to get wrong.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, assert_never
from uuid import UUID

from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.slices.payload import deserialize_or_raise


@dataclass(frozen=True)
class SetupDefined:
    """A beamline's values for an operation were written down here.

    Defined rather than registered: nothing anywhere holds these values
    under this name for this operation at this beamline until this event
    says so, and the record IS the setup. That is the split the genesis
    verbs draw in the glossary.

    `setup_name`, not `name`. Qualified because the personal-data check
    reads field names and cannot tell a setup's name from a person's, the
    same reason `OperationDefined` carries `operation_name`. The state keeps
    the bare `name`, where the aggregate it hangs off supplies the
    qualifier.

    `beamline` is not qualified, for the reason a procedure's is not:
    nothing else on this row could be a beamline, and the personal-data
    check has no reason to look at the word.
    """

    setup_id: UUID
    beamline: str
    operation_id: UUID
    setup_name: str
    settings: dict[str, Any]
    settings_schema: dict[str, Any]
    occurred_at: datetime


@dataclass(frozen=True)
class SetupRevised:
    """The next revision of a setup's values and their schema.

    Revised rather than updated or edited: the revision before it stays on
    the stream exactly as it was written, and folding the stream that far
    reads it back.

    No reason rides it. Why a value changed is free text, which is where a
    person's name arrives in a table nothing can edit, and who revised it
    is on the envelope already.
    """

    setup_id: UUID
    revision: int
    settings: dict[str, Any]
    settings_schema: dict[str, Any]
    occurred_at: datetime


SetupEvent = SetupDefined | SetupRevised
"""Every event that can appear on a Setup stream.

A new member is a new class added here and to this alias, never a field
bolted onto an event already in the log. Adding one without teaching the
evolver about it is a type error, because the wildcard arm there calls
`assert_never`.
"""


def to_payload(event: SetupEvent) -> dict[str, Any]:
    """Render an event as the primitives that get stored."""
    match event:
        case SetupDefined():
            return {
                "setup_id": str(event.setup_id),
                "beamline": event.beamline,
                "operation_id": str(event.operation_id),
                "setup_name": event.setup_name,
                "settings": event.settings,
                "settings_schema": event.settings_schema,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case SetupRevised():
            return {
                "setup_id": str(event.setup_id),
                "revision": event.revision,
                "settings": event.settings,
                "settings_schema": event.settings_schema,
                "occurred_at": event.occurred_at.isoformat(),
            }
        case _:
            assert_never(event)


def from_stored(stored: StoredEvent) -> SetupEvent:
    """Rebuild an event from its stored row.

    `extra` carries `ValueError` because the constructors in each arm raise
    it on malformed input: a string that is not a UUID, a string that is not
    a timestamp, and a revision that is not a number. Without it those
    escape as themselves, naming the field rather than the event.

    The settings and their schema come back as whatever the row holds, with
    no check that they would still be accepted today. They were checked
    when they were written and the row cannot have changed since; checking
    them here would mean a validator that later grew stricter could stop a
    setup's stream from loading at all, and with it every earlier revision.
    """
    payload = stored.payload
    match stored.event_type:
        case "SetupDefined":
            return deserialize_or_raise(
                "SetupDefined",
                lambda: SetupDefined(
                    setup_id=UUID(payload["setup_id"]),
                    beamline=payload["beamline"],
                    operation_id=UUID(payload["operation_id"]),
                    setup_name=payload["setup_name"],
                    settings=payload["settings"],
                    settings_schema=payload["settings_schema"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case "SetupRevised":
            return deserialize_or_raise(
                "SetupRevised",
                lambda: SetupRevised(
                    setup_id=UUID(payload["setup_id"]),
                    revision=int(payload["revision"]),
                    settings=payload["settings"],
                    settings_schema=payload["settings_schema"],
                    occurred_at=datetime.fromisoformat(payload["occurred_at"]),
                ),
                extra=(ValueError,),
            )
        case unknown:
            msg = f"Unknown Setup event_type: {unknown!r}"
            raise ValueError(msg)


__all__ = ["SetupDefined", "SetupEvent", "SetupRevised", "from_stored", "to_payload"]
