"""Operation state, its name value object, and its domain errors.

An Operation is something this system can be asked to run, written down: a name
the engine knows it by, and a schema saying what parameters a
run of it must supply.

## Why a name here, when neither an actor nor a policy carries one

An actor's name labels a party that exists whether or not this system has
heard of it, so leaving it out costs nothing and keeps a person's name
out of a log that cannot be edited. An operation's name is different in kind:
it is how the engine identifies what to run, so an operation without
one names nothing and there is no act to record. Functional identity,
not decoration.

Two operations may share a name, and nothing here stops that. One routine
constrained two ways is two operations, and which one a run step
cites is what says how it was constrained.

## Why the schema is required

The shared carrier-side validator accepts an absent schema and refuses
the values that would have gone with it, which is the four-cell posture
in docs/reference/conventions.md. An Operation closes that cell earlier, at
definition, by requiring a schema. An operator with nothing to constrain
declares a schema that constrains nothing and says so in the record; the
alternative is an operation that can never refuse a parameter, with nothing
saying whether that was meant.

So the absent-schema row of that table is unreachable from here. It stays
in the shared helper because the helper is shared and the next declarer
may want it.

## Retired, and what that does and does not stop

An operation is retired when no engine answers to it any longer. The
record keeps it, readable, and stops offering it: nothing new may cite it,
which means no procedure composed around it, no proposal put forward for
it, no setup defined for it, and no dispatch of a procedure that runs it.
Each of those would be work that waits forever, or values nothing will
apply, because the thing that would have answered it has gone.

What it does not touch is anything already cited. A procedure composed
around it stays readable and so does every execution that ran it, because
the record of what was asked for does not become false when the asking
stops. Retiring is not deleting.

## Device use, which the facility declares

Whether a run of the routine drives devices at the station that runs it.
A collection drives a detector and a stage; a transfer to another
facility, or a reconstruction there, drives nothing here and takes hours.
A run composed for a proposal used to claim the station's devices
whatever it ran, which held them for the whole of a transfer, and nothing
on the record could say otherwise because nothing had asked.

So the facility says, once per operation, and the answer is a third state
until it does. Undeclared is not a quiet false: a run of an undeclared
operation is composed exactly as it was before anybody could declare one,
and a composition of several runs that needs to know is refused instead,
naming the operation. Once declared it stays declared, for the reason a
schema is never edited: a wrong answer is corrected by defining another
operation, so every procedure composed under the first one still reads as
what it was composed under.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from keeper.shared.bounded_text import bounded_name

OPERATION_NAME_MAX_LENGTH = 200
"""How long an operation name may be after trimming.

Matches the bound the policy aggregate puts on a command name, which is
the nearest thing already in the tree: both are identifiers some other
system minted and this one stores whole.
"""


class InvalidOperationNameError(ValueError):
    """An operation name was empty, whitespace-only, or over the length bound.

    A `ValueError`, unlike the other errors here, because it says the
    input was never well-formed rather than that a rule about existing
    state was broken. That is the split the rejection table in
    docs/reference/patterns.md draws, and it is why this one maps to 400
    while the two below map to 404 and 409.
    """

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Operation name must be 1 to {OPERATION_NAME_MAX_LENGTH} characters after "
            f"trimming (got {len(value.strip())})"
        )


class InvalidOperationParametersSchemaError(ValueError):
    """The declared parameters schema is not one this system will store.

    Carries the reason the shared validator gave, which names the
    keyword or the draft that was wrong. The message is the operator's
    only guide to fixing the document they sent, so it is passed through
    rather than replaced with a generic line.
    """


class OperationNotFoundError(Exception):
    """A command or query named an operation id with no stream behind it."""

    def __init__(self, operation_id: UUID) -> None:
        super().__init__(f"Operation {operation_id} not found")
        self.operation_id = operation_id


class OperationAlreadyExistsError(Exception):
    """Definition was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because a defining handler
    mints a fresh id and a fresh id has no history. It exists so the
    decider states the precondition it relies on rather than assuming it,
    and so a caller supplying its own id is refused instead of writing a
    second genesis event onto a live stream.
    """

    def __init__(self, operation_id: UUID) -> None:
        super().__init__(f"Operation {operation_id} already exists")
        self.operation_id = operation_id


class OperationStatus(StrEnum):
    """Whether this system still offers an operation to be run.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step, which is the spelling every status here uses.

    Both are this system's own bookkeeping and neither is a claim about
    an engine. `ACTIVE` says nothing has retired the operation, not that
    anything answers to it: an engine can go away without telling this
    system, and the record learns it only when somebody retires the
    operation.
    """

    ACTIVE = "Active"
    RETIRED = "Retired"


class OperationCannotBeRetiredError(Exception):
    """Retirement was asked for an operation already retired.

    Refused only from `RETIRED`, the way a device's retirement is. A second
    row would say nothing the stream does not already say.
    """

    def __init__(self, operation_id: UUID, status: OperationStatus) -> None:
        super().__init__(f"Operation {operation_id} cannot be retired: it is already {status}")
        self.operation_id = operation_id
        self.status = status


class OperationCannotBeCitedError(Exception):
    """Something new named an operation that has been retired.

    Raised wherever a new record would rest on the operation: a procedure
    whose run cites it, a proposal put forward for it, a setup defined for
    it, and a dispatch of a procedure that runs it. One class for the four,
    because the refusal is the same fact each time and so is the caller's
    next move, which is to cite an operation something still answers to.

    Carries the status rather than only the id, the way
    `ExecutionCannotBeClaimedError` does, so a caller is told why rather
    than only that.
    """

    def __init__(self, operation_id: UUID, status: OperationStatus) -> None:
        super().__init__(
            f"Operation {operation_id} cannot be cited: it is {status}, and nothing "
            "answers to a retired operation"
        )
        self.operation_id = operation_id
        self.status = status


class OperationDeviceUseCannotBeDeclaredError(Exception):
    """A declaration of device use arrived for an operation that cannot take one.

    Two causes, one class, told apart by what the error carries, which is
    the shape `SetupCannotBeRevisedError` takes. `status` Retired is the
    first cause and is the one reported when both hold, because nothing
    composes a run of a retired operation and a declaration would govern
    nothing. Otherwise `drives_devices` is set and says which way the
    operation is declared already. Both attributes are always the
    operation's own, whichever cause the message names. R6 is about not
    collapsing several verbs, and there is one verb here.

    A second declaration is refused whichever way it points, including the
    way the first one did. That makes a caller's own retry a 409 rather
    than a success, and the held answer on the error is what lets that
    caller see its first attempt landed. Accepting a repeat that agreed
    and refusing one that did not would make the outcome depend on a
    value the caller may not know, which is a worse contract than one
    answer for both.
    """

    def __init__(
        self,
        operation_id: UUID,
        *,
        status: OperationStatus,
        drives_devices: bool | None,
    ) -> None:
        if status is OperationStatus.RETIRED:
            reason = f"it is {status}, and nothing answers to a retired operation"
        else:
            reason = (
                f"it is already declared drives_devices = {str(drives_devices).lower()}, "
                "and a declaration is made once: a wrong one is corrected by defining "
                "another operation"
            )
        super().__init__(f"Operation {operation_id}'s device use cannot be declared: {reason}")
        self.operation_id = operation_id
        self.status = status
        self.drives_devices = drives_devices


class OperationCannotBeComposedError(Exception):
    """A run of this operation cannot be composed with the device use it was asked for.

    Raised by the seam that composes proposals into work, and by nothing
    an authored procedure passes through: a composer writing a procedure
    states each run's devices itself, and this is about the runs nobody
    stated anything for.

    Two causes, told apart by `drives_devices`, which is the declaration
    the run met. None means nothing has declared whether the operation's
    runs drive devices, and the run is one of several composed together,
    which has to know what each of them touches. True means the operation
    is declared to drive devices and its caller said the run drives none,
    which would compose a step that runs beside another over the same
    motor. The fix differs, a declaration on the operation against scopes
    from the caller, and the message says which.

    A 409, because both are a request meeting a fact the record holds,
    and both go through once that fact or the request changes.

    `index` is the run's place in what was being composed, counted from
    zero, because one composition may run the same operation twice and
    the caller has to be able to find the one refused.
    """

    def __init__(self, operation_id: UUID, index: int, *, drives_devices: bool | None) -> None:
        if drives_devices is None:
            reason = (
                "nothing has declared whether its runs drive devices, and a "
                "composition of several runs has to know what each of them touches, "
                "so the operation's device use has to be declared first"
            )
        else:
            reason = (
                "it is declared to drive devices, and its run was asked to drive "
                "none. Name the devices it may touch as scopes instead"
            )
        super().__init__(f"Run {index} of operation {operation_id} cannot be composed: {reason}")
        self.operation_id = operation_id
        self.index = index
        self.drives_devices = drives_devices


@bounded_name(max_length=OPERATION_NAME_MAX_LENGTH, error_class=InvalidOperationNameError)
@dataclass(frozen=True)
class OperationName:
    """The name the engine knows this routine by.

    Trimmed and length-bounded on construction. Wrapped rather than left
    a bare string so that the check runs everywhere the name enters the
    model: once in the decider, on the way in, and again in the evolver,
    on the way back out of the log.
    """

    value: str


@dataclass(frozen=True)
class Operation:
    """A runnable routine, as the fold leaves it.

    `status` is the only field the fold computes rather than copies. It
    is derived from which events the stream carries and stored nowhere,
    so it cannot disagree with the history behind it.

    `drives_devices` is the facility's declaration, copied off the event
    that made it, and None until one has. The default is None for the
    same reason: every operation defined before the question could be
    asked folds into an operation nobody has answered it for, which is
    what it is.
    """

    id: UUID
    name: OperationName
    parameters_schema: dict[str, Any]
    status: OperationStatus
    drives_devices: bool | None = None

    @property
    def is_retired(self) -> bool:
        """Whether this system has stopped offering the operation.

        Asked by every decider that refuses a retired operation, so the
        answer is written once rather than as a comparison in each.
        """
        return self.status is OperationStatus.RETIRED


__all__ = [
    "OPERATION_NAME_MAX_LENGTH",
    "InvalidOperationNameError",
    "InvalidOperationParametersSchemaError",
    "Operation",
    "OperationAlreadyExistsError",
    "OperationCannotBeCitedError",
    "OperationCannotBeComposedError",
    "OperationCannotBeRetiredError",
    "OperationDeviceUseCannotBeDeclaredError",
    "OperationName",
    "OperationNotFoundError",
    "OperationStatus",
]
