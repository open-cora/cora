"""Walk state, its value objects, and its domain errors.

A Walk is one traversal of a procedure, as reported by whatever drove it.

## What a walk is, against what a run is

A run is one execution of a plan, and a plan is a name an engine knows a
routine by. A walk is one traversal of a procedure, and a procedure is a
routine composed outside any engine: moves, settings and acquisitions in
an order, each declaring the devices it touches. The two pairs are the
same shape at two scales, which is why they share a context.

Most steps cause no run at all. A move drives a motor and opens nothing,
so a walk cannot be recorded as a run without losing every step that was
not an acquisition, which is most of them.

## Why the step list is copied onto the record

A walk carries the steps it was asked to perform rather than citing a
definition held elsewhere. Two reasons, and the second is the one that
would survive a Procedure aggregate arriving.

Nothing holds procedures yet, so there is nothing to cite. And a walk
that cited one would become a record of the wrong thing the moment that
procedure was edited, which is why a history is stored rather than a
pointer to the definition that produced it.

## Why a step's outcome is not a status

`RunStatus` is derived in the fold from which event the stream carries.
A step's outcome is derived the same way, from which of the four step
events landed, and for the same reason: an outcome written onto a
payload could contradict the event it rode in on.

The four are not degrees of success. `DONE` means the seam returned
without raising and says nothing about whether the science worked, which
is the distinction the acquisition findings forced and the one word here
most likely to be read as more than it is. `REFUSED` is the only good
news in the set: a claim conflict stopped the step before it touched
anything. `BROKEN` means the seam raised. `SKIPPED` means the walk had
already stopped before reaching this step.

## Why a broken step keeps a class name and not a message

The exception's type is recorded and its message is not. A message from
a driver is free text of unknown provenance heading for a row nobody can
edit, which is the field most likely to end up holding a path with a
person's name in it. The type separates a motor that would not move from
a typo in an adapter, which is the distinction a reader actually needs,
and the message stays in the logs of whatever was driving.

## No status on the walk

Two states, in flight and ended, so `ended` is a boolean. A third state
arrives when something can say a walk was abandoned, which needs
something watching rather than another value, and an enum earns its
place then.
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from aroc.shared.bounded_text import bounded_name
from aroc.shared.identifier import Identifier

WALK_PROCEDURE_NAME_MAX_LENGTH = 200
"""How long a procedure's name may be after trimming.

The same bound a plan name carries, because the two are the same kind of
thing: a name some other system minted for a routine, stored whole.
"""

WALK_STEP_MAX_LENGTH = 500
"""How long one step's description may be after trimming.

Longer than a name because a step describes itself rather than being
labelled: what it does, to which record, over which devices.
"""

WALK_MAX_STEPS = 1000
"""How many steps one walk may hold.

A bound rather than a limit anyone is expected to reach. It is here
because the whole list rides the genesis event, so an unbounded
procedure is an unbounded row in a table nothing can edit.

A routine with more steps than this is one an engine should be running.
A conductor composes steps that each declare the devices they touch,
which is worth its cost for tens of steps and is the wrong shape for a
raster with thousands.
"""


class InvalidWalkProcedureNameError(ValueError):
    """A procedure name was empty, whitespace-only, or over the length bound."""

    def __init__(self, value: str) -> None:
        super().__init__(
            f"Procedure name must be 1 to {WALK_PROCEDURE_NAME_MAX_LENGTH} characters "
            f"after trimming (got {len(value.strip())})"
        )


class InvalidWalkStepsError(ValueError):
    """The step list was empty, too long, or held a step that was neither.

    One error for three failures because all three say the same thing to
    a caller: the list of steps sent is not one this system will store.
    The message names which of the three it was.
    """


class InvalidStepReportError(ValueError):
    """A step report carried a detail that does not belong to its outcome.

    Each outcome has exactly one shape: a done step may name the run it
    opened, a broken step names what was raised, and a refused or skipped
    step names nothing. A report carrying a cause alongside a done
    outcome is a caller that has confused two of them, and dropping the
    field quietly would lose whichever one was right.

    A `ValueError` because it says the input was never well-formed,
    rather than that a rule about existing state was broken, which is
    the split that sends this to 400 and the errors below to 404 and
    409.
    """


class InvalidWalkFilterError(ValueError):
    """A listing was asked for half of a reference, which names nothing.

    Both surfaces take the scheme and the value as two parameters,
    because a scheme has no pattern and a single joined string could not
    be split with any confidence. That makes one half arriving alone a
    shape both of them can produce, so the refusal lives in the domain
    rather than twice at the edges.
    """

    def __init__(self, scheme: str | None, value: str | None) -> None:
        super().__init__(
            "A walk reference filter needs both halves or neither "
            f"(got scheme={scheme!r}, value={value!r})"
        )
        self.scheme = scheme
        self.value = value


class WalkNotFoundError(Exception):
    """A command or query named a walk id with no stream behind it."""

    def __init__(self, walk_id: UUID) -> None:
        super().__init__(f"Walk {walk_id} not found")
        self.walk_id = walk_id


class WalkAlreadyExistsError(Exception):
    """A walk was reported against an id that already has a stream."""

    def __init__(self, walk_id: UUID) -> None:
        super().__init__(f"Walk {walk_id} already exists")
        self.walk_id = walk_id


class WalkAlreadyEndedError(Exception):
    """Something arrived for a walk that has already been closed.

    Raised by both the step report and the ending, which is why it names
    neither. A walk that has ended takes nothing further: the record is
    what it was when it closed, and a late step would rewrite history
    that a reader may already have acted on.
    """

    def __init__(self, walk_id: UUID) -> None:
        super().__init__(f"Walk {walk_id} has already ended")
        self.walk_id = walk_id


class WalkStepOutOfRangeError(Exception):
    """A step was reported at an index the walk's step list does not have.

    The step list is fixed at the genesis, so this means the caller and
    the record disagree about what is being walked. Reporting it as a
    refusal rather than growing the list is deliberate: a walk whose
    steps could be appended to afterwards would have no honest answer to
    how many were never reached.
    """

    def __init__(self, walk_id: UUID, index: int, step_count: int) -> None:
        super().__init__(
            f"Walk {walk_id} has {step_count} steps, so step {index} is not one of them"
        )
        self.walk_id = walk_id
        self.index = index
        self.step_count = step_count


class WalkStepAlreadyReportedError(Exception):
    """A step already has an outcome, and a second one arrived for it.

    Refused rather than accepted as a correction. An outcome is what the
    driver observed at the time, and a second reading of one step is
    either a repeated send, which the idempotency wrapper is there to
    absorb, or two drivers reporting one walk, which is a fault worth
    surfacing rather than resolving by last-write-wins.
    """

    def __init__(self, walk_id: UUID, index: int) -> None:
        super().__init__(f"Step {index} of walk {walk_id} has already been reported")
        self.walk_id = walk_id
        self.index = index


class StepOutcome(StrEnum):
    """How one step of a walk ended.

    Values are PascalCase strings so a log line or a response body reads
    without a mapping step, which is the choice `RunStatus` made.

    Every value is terminal for its step. A step does not pause and does
    not resume: whatever drove it either returned, was refused before it
    started, raised, or was never reached.
    """

    DONE = "Done"
    REFUSED = "Refused"
    BROKEN = "Broken"
    SKIPPED = "Skipped"


@bounded_name(max_length=WALK_PROCEDURE_NAME_MAX_LENGTH, error_class=InvalidWalkProcedureNameError)
@dataclass(frozen=True)
class WalkProcedureName:
    """The name the routine this walk traversed was composed under.

    Trimmed and length-bounded on construction, so the check runs both
    in the decider on the way in and in the evolver on the way back out
    of the log.

    Not a reference to anything. Nothing holds procedures, so two walks
    naming the same procedure are two records that happen to agree, and
    this system cannot say they traversed the same steps. The step list
    on each record is what can be compared.
    """

    value: str


def validated_steps(raw: tuple[str, ...]) -> tuple[str, ...]:
    """Trim a step list and refuse one this system will not store.

    Called on the way in by the decider and on the way out by the
    evolver, which is the same both-directions check a value object
    gives. A function rather than a value object because the thing being
    validated is the list, and a type per step would have to be unwrapped
    at every place a reader wants the text.
    """
    if not raw:
        msg = "A walk must name at least one step, because a walk of nothing records nothing"
        raise InvalidWalkStepsError(msg)
    if len(raw) > WALK_MAX_STEPS:
        msg = (
            f"A walk may hold at most {WALK_MAX_STEPS} steps and this one names {len(raw)}; "
            "a routine that long belongs to an engine rather than to a conductor"
        )
        raise InvalidWalkStepsError(msg)
    trimmed = tuple(step.strip() for step in raw)
    for index, step in enumerate(trimmed):
        if not step:
            msg = f"Step {index} describes nothing after trimming"
            raise InvalidWalkStepsError(msg)
        if len(step) > WALK_STEP_MAX_LENGTH:
            msg = f"Step {index} is {len(step)} characters and the bound is {WALK_STEP_MAX_LENGTH}"
            raise InvalidWalkStepsError(msg)
    return trimmed


@dataclass(frozen=True)
class WalkStep:
    """One step of a walk, as the fold leaves it.

    `describes` comes from the genesis and never changes. Everything else
    is None until an outcome lands, and each field belongs to exactly one
    outcome: `engine_reference` to a step that was done and opened a run,
    `cause` to a break. A step that was refused or skipped adds nothing
    at all.

    A refusal carries no detail, and that is a boundary rather than a
    gap. Which step held the device and which scopes collided are facts
    about a ledger that lives in the driver's process, is not durable by
    its own argument, and names things this system neither mints nor
    resolves. Nothing here can act on either, so carrying them would be
    keeping a driver's working notes in an append-only table.

    `engine_reference` is what the engine calls the run this step caused,
    and it is a correlation hint rather than a key. Nothing here checks
    that such a run exists, and nothing could: whatever watches the
    engine records that run on its own schedule, so at the moment a step
    is reported the run it caused may not be recorded anywhere yet.
    `docs/reference/conducting.md` holds the argument.

    `cause` is an exception's class name, never its message. See the
    module docstring.
    """

    describes: str
    outcome: StepOutcome | None = None
    engine_reference: str | None = None
    cause: str | None = None

    @property
    def is_reported(self) -> bool:
        """Whether an outcome has landed for this step."""
        return self.outcome is not None


@dataclass(frozen=True)
class Walk:
    """One traversal of a procedure, as the fold leaves it.

    `reference` is what whatever drove this walk calls it, minted before
    the first step ran because there is no handle at that moment. It is
    an open-scheme pair for the reason a run's is: the scheme names the
    driver's own vocabulary, and which driver a deployment runs is a
    deployment's fact.

    `steps` is index-aligned with the list the genesis carried, and stays
    the same length for the life of the stream.

    `ended` says a close was reported. It does not say every step was.
    A walk that stopped at its first failure reports the rest as skipped
    and then ends, so the two are different facts and both are readable.
    """

    id: UUID
    reference: Identifier
    procedure_name: WalkProcedureName
    steps: tuple[WalkStep, ...]
    ended: bool

    @property
    def step_count(self) -> int:
        """How many steps the walk was asked to perform."""
        return len(self.steps)

    @property
    def reported_count(self) -> int:
        """How many steps have an outcome.

        Short of `step_count` on a walk still in flight, and short of it
        on one that ended without reporting the rest, which is what a
        record left behind by a driver that died looks like.
        """
        return sum(1 for step in self.steps if step.is_reported)


__all__ = [
    "WALK_MAX_STEPS",
    "WALK_PROCEDURE_NAME_MAX_LENGTH",
    "WALK_STEP_MAX_LENGTH",
    "InvalidStepReportError",
    "InvalidWalkFilterError",
    "InvalidWalkProcedureNameError",
    "InvalidWalkStepsError",
    "StepOutcome",
    "Walk",
    "WalkAlreadyEndedError",
    "WalkAlreadyExistsError",
    "WalkNotFoundError",
    "WalkProcedureName",
    "WalkStep",
    "WalkStepAlreadyReportedError",
    "WalkStepOutOfRangeError",
    "validated_steps",
]
