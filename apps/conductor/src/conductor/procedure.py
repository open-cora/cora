"""A procedure, its steps, and what each step has to declare.

A procedure is composed here rather than known by an engine, which is the
whole of what separates it from a plan. A plan names a routine some engine
already has; its name is a handle in that engine's vocabulary. A
procedure's steps are authored on this side, and nothing outside knows
what one is.

## Why writing splits into two steps

`Move` and `Set` differ in what the step is owed when it returns, not in
what it writes. A `Move` is owed a record that arrived and stopped
moving; a `Set` is owed a record that reads its value back. `seams.py`
carries the argument for keeping those apart, and the short form is that
a single step would have to accept the weaker promise silently whenever
the record could not support the stronger one.

Which to write is decided by the record, and the author knows: a motor
is moved, and a scan type, a file name or an exposure count is set.

## Why an acquisition step declares its devices and a move does not

A move names one record, so its claim is that record and there is nothing
for an author to get wrong. A set is the same.

An acquisition step cannot work that way. Which devices a plan touches is
inside the plan, in the engine, and `spikes/bluesky_adapter/FINDINGS.md`
already found that a start document describes one invocation rather than
the routine, so there is nothing to derive a device list from either. The
conductor therefore cannot know, and a step that let the author leave it
unsaid would default to claiming nothing, which is precisely the
undeclared scan that `spikes/conductor/FINDINGS.md` watched get corrupted
four different ways.

So an acquisition step with an empty claim is refused where it is built.
The cost is an author writing down what their plan moves. The alternative
is a procedure whose most dangerous step is the one that claims least.

Not every engine is as silent as Bluesky about this.
`spikes/tomoscan_adapter/FINDINGS.md` records that TomoScan publishes its
own device map, as records whose values are the names of other records,
so an adapter there can check a declared claim against what the engine
will actually reach for. That is an adapter's check to offer and not a
reason to stop requiring the declaration, since the engine that cannot
be asked is still the common case.

## Why a bound is optional and a claim is not

An undeclared claim defaults to claiming nothing, which is the dangerous
direction. An undeclared bound defaults to waiting, which is the
patient one. A procedure written before anyone knows how long a plan
takes is worth being able to write, and the step that omits a bound says
plainly that it will wait as long as the engine does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from conductor.claims import Claim, Scope

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from conductor.seams import Setting


class InvalidProcedureError(ValueError):
    """A procedure or one of its steps could not be built as described."""


@dataclass(frozen=True, slots=True)
class Move:
    """Send one record to one position, and wait for it to stop there."""

    record: str
    to: float

    def __post_init__(self) -> None:
        if not self.record.strip():
            raise InvalidProcedureError("a move needs a record to move")

    @property
    def claim(self) -> Claim:
        """The record itself, derived rather than declared."""
        return Claim(scopes=frozenset({Scope.record(self.record)}))

    @property
    def describes(self) -> str:
        return f"move {Scope.record(self.record)} to {self.to}"


@dataclass(frozen=True, slots=True)
class Set:
    """Send one record to one value, and wait for it to read that value back.

    The value is `Setting` rather than a number because the records a
    procedure configures are mostly not numbers: an enumeration is
    written as its choice string, a file name and a path as text.
    """

    record: str
    to: Setting

    def __post_init__(self) -> None:
        if not self.record.strip():
            raise InvalidProcedureError("a set needs a record to write")

    @property
    def claim(self) -> Claim:
        """The record itself, on the same grounds a move's claim is derived.

        A configuration record is as capable of being fought over as a
        motor, and more quietly: two walks that disagree about a scan
        type produce one scan of the wrong kind rather than a collision
        anyone can see.
        """
        return Claim(scopes=frozenset({Scope.record(self.record)}))

    @property
    def describes(self) -> str:
        return f"set {Scope.record(self.record)} to {self.to!r}"


@dataclass(frozen=True, slots=True)
class Acquire:
    """Ask the engine to run a plan, over devices the author names."""

    plan: str
    claim: Claim
    parameters: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    bound: float | None = None
    """Seconds the author allows this plan, or `None` to wait indefinitely."""

    def __post_init__(self) -> None:
        if not self.plan.strip():
            raise InvalidProcedureError("an acquisition needs a plan to run")
        if not self.claim.scopes:
            raise InvalidProcedureError(
                f"the acquisition of {self.plan!r} must declare the devices it touches, "
                "because nothing here can derive them from the plan"
            )
        if self.bound is not None and self.bound <= 0:
            raise InvalidProcedureError(
                f"the acquisition of {self.plan!r} was given a bound of {self.bound}, and a "
                "plan cannot be allowed no time at all. Leave it unset to wait indefinitely"
            )

    @property
    def describes(self) -> str:
        within = "" if self.bound is None else f" within {self.bound}s"
        return f"acquire {self.plan} over {self.claim}{within}"


Step = Move | Set | Acquire
"""What a procedure is made of. Three kinds, and all of them hold a claim."""


@dataclass(frozen=True, slots=True)
class Procedure:
    """An ordered routine this system composed, and can be asked to walk."""

    name: str
    steps: Sequence[Step]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise InvalidProcedureError("a procedure needs a name")
        if not self.steps:
            raise InvalidProcedureError(f"the procedure {self.name!r} has no steps")
