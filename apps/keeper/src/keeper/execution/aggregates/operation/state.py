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

## Place use, which the facility declares too

Which of a run's parameters name a place. A move names two, where its data
leaves and where it lands; a collection may name the place its scan is
written; a process names the place it runs at. A pursuit authorizes some
places and refuses work naming any other, and it can only do that if
something says which values in a run are places. Nothing here can tell by
looking: a parameter is a name and a schema, and `at` holding a place is a
convention of the facility's register rather than anything this system
reads.

So the facility says, once per operation, beside its device use and for
the same reasons. Undeclared is a third state here as well, and it is
refused wherever a run's places have to be known, because a run nobody
can read the places of is a run that could move data anywhere.
"""

from collections.abc import Mapping
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


class InvalidOperationPlaceUseError(ValueError):
    """A declaration of place use named parameters it cannot.

    A `ValueError` and a 400, beside the name and the schema, because each
    cause is a declaration that could never be right for this operation
    however long anybody waited: a parameter named twice, named as a place
    and as a compute place both, missing from the schema the operation was
    defined with, or declared there as something other than text, which a
    place name always is.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"Operation place use is invalid: {reason}")
        self.reason = reason


@dataclass(frozen=True)
class PlaceUse:
    """Which of a run's parameters name a place, as the facility declared it.

    `place_parameters` name places a run reads or writes data at: both ends
    of a move, and where a collection lands. `compute_place_parameters`
    name where a run processes, which for a process is the place it runs
    at, and its input and output are inside that place by construction.

    Parameters rather than places. The places are a run's values and differ
    from run to run; which of its parameters hold one is a fact about the
    routine and the same for every run of it, so it is said once, on the
    operation. Whatever checks a run's places reads the values it carries
    in these parameters, and a parameter a run leaves out names nothing.

    Both may be empty, and that is an answer rather than a gap: an
    operation whose runs name no place, such as one that only drives
    devices, says so. An operation nobody has declared is the third state.

    Checked on construction for what holds of any declaration, so the same
    refusal runs on the way in and on the way back out of the log. Whether
    each parameter is one the operation takes needs its schema, and the
    decider is where that is asked.
    """

    place_parameters: tuple[str, ...]
    compute_place_parameters: tuple[str, ...]

    def __post_init__(self) -> None:
        """Refuse an empty parameter name, and a parameter named twice."""
        named = (*self.place_parameters, *self.compute_place_parameters)
        if any(not parameter.strip() for parameter in named):
            raise InvalidOperationPlaceUseError("a parameter name is empty")
        if len(set(named)) != len(named):
            raise InvalidOperationPlaceUseError(
                "a parameter is named more than once, and one parameter names a place "
                "or a compute place, not both"
            )

    def places_in(self, parameters: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        """Each place-naming parameter these values carry, paired with the place it names."""
        return tuple(
            (parameter, str(parameters[parameter]))
            for parameter in self.place_parameters
            if parameter in parameters
        )

    def compute_places_in(self, parameters: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        """Each compute-place parameter these values carry, paired with the place it names."""
        return tuple(
            (parameter, str(parameters[parameter]))
            for parameter in self.compute_place_parameters
            if parameter in parameters
        )


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


class OperationPlaceUseCannotBeDeclaredError(Exception):
    """A declaration of place use arrived for an operation that cannot take one.

    The device use error's shape, for the same two causes. `status`
    Retired is the first and is the one reported when both hold, because
    nothing composes a run of a retired operation. Otherwise `place_use` is
    set and is the declaration already made, which is how a caller's own
    retry learns that its first attempt landed.

    Refused a second time whatever it says, including what the first one
    said, for the reason a second declaration of device use is.
    """

    def __init__(
        self,
        operation_id: UUID,
        *,
        status: OperationStatus,
        place_use: PlaceUse | None,
    ) -> None:
        if status is OperationStatus.RETIRED or place_use is None:
            reason = f"it is {status}, and nothing answers to a retired operation"
        else:
            reason = (
                f"it is already declared to name places in {list(place_use.place_parameters)} "
                f"and compute places in {list(place_use.compute_place_parameters)}, and a "
                "declaration is made once: a wrong one is corrected by defining another "
                "operation"
            )
        super().__init__(f"Operation {operation_id}'s place use cannot be declared: {reason}")
        self.operation_id = operation_id
        self.status = status
        self.place_use = place_use


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

    `place_use` is the other declaration, said the same way and None on
    the same terms.
    """

    id: UUID
    name: OperationName
    parameters_schema: dict[str, Any]
    status: OperationStatus
    drives_devices: bool | None = None
    place_use: PlaceUse | None = None

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
    "InvalidOperationPlaceUseError",
    "Operation",
    "OperationAlreadyExistsError",
    "OperationCannotBeCitedError",
    "OperationCannotBeComposedError",
    "OperationCannotBeRetiredError",
    "OperationDeviceUseCannotBeDeclaredError",
    "OperationName",
    "OperationNotFoundError",
    "OperationPlaceUseCannotBeDeclaredError",
    "OperationStatus",
    "PlaceUse",
]
