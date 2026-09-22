"""A procedure, its steps, and what each step has to declare.

A procedure is composed here rather than known by an engine, which is the
whole of what separates it from a plan. A plan names a routine some engine
already has; its name is a handle in that engine's vocabulary. A
procedure's steps are authored on this side, and nothing outside knows
what one is.

## Why an acquisition step declares its devices and a move does not

A move names one record, so its claim is that record and there is nothing
for an author to get wrong.

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
class Move:
    """Send one record to one value."""

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
class Acquire:
    """Ask the engine to run a plan, over devices the author names."""

    plan: str
    claim: Claim
    parameters: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.plan.strip():
            raise InvalidProcedureError("an acquisition needs a plan to run")
        if not self.claim.scopes:
            raise InvalidProcedureError(
                f"the acquisition of {self.plan!r} must declare the devices it touches, "
                "because nothing here can derive them from the plan"
            )

    @property
    def describes(self) -> str:
        return f"acquire {self.plan} over {self.claim}"


Step = Move | Acquire
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
