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
    """

    id: UUID
    name: OperationName
    parameters_schema: dict[str, Any]
    status: OperationStatus

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
    "OperationCannotBeRetiredError",
    "OperationName",
    "OperationNotFoundError",
    "OperationStatus",
]
