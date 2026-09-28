"""A procedure, its steps, and what each step has to declare.

A procedure is composed here rather than known by an engine, which is the
whole of what separates it from an operation. An operation names a routine
some engine already has; its name is a handle in that engine's vocabulary. A
procedure's steps are authored on this side, and nothing outside knows
what one is.

## Why a run step declares its devices and a set does not

A set names one record, so its claim is that record and there is nothing
for an author to get wrong.

A run step cannot work that way. Which devices a routine touches is
inside the routine, in the engine, and a spike
already found that a start document describes one invocation rather than
the routine, so there is nothing to derive a device list from either. The
conductor therefore cannot know, and a step that let the author leave it
unsaid would default to claiming nothing, which is precisely the
undeclared scan that a spike watched get corrupted
four different ways.

So a run step with an empty claim is refused where it is built.
The cost is an author writing down what their routine moves. The alternative
is a procedure whose most dangerous step is the one that claims least.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING

from conductor.claims import Claim, Scope

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class InvalidProcedureError(ValueError):
    """A procedure or one of its steps could not be built as described."""


@dataclass(frozen=True, slots=True)
class Set:
    """Send one record to one value."""

    record: str
    to: float

    def __post_init__(self) -> None:
        if not self.record.strip():
            raise InvalidProcedureError("a set needs a record to write to")

    @property
    def claim(self) -> Claim:
        """The record itself, derived rather than declared."""
        return Claim(scopes=frozenset({Scope.record(self.record)}))

    @property
    def describes(self) -> str:
        return f"set {Scope.record(self.record)} to {self.to}"


@dataclass(frozen=True, slots=True)
class Run:
    """Ask the engine to run a plan, over devices the author names."""

    plan: str
    claim: Claim
    parameters: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.plan.strip():
            raise InvalidProcedureError("a run needs a plan to run")
        if not self.claim.scopes:
            raise InvalidProcedureError(
                f"the run of {self.plan!r} must declare the devices it touches, "
                "because nothing here can derive them from the plan"
            )

    @property
    def describes(self) -> str:
        return f"run {self.plan} over {self.claim}"


Step = Set | Run
"""What a procedure is made of. Two kinds, and both hold a claim."""


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
