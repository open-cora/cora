"""A procedure, its steps, and what each step has to declare.

A procedure is composed here rather than known by an engine, which is the
whole of what separates it from an operation. An operation names a routine
some engine already has; its name is a handle in that engine's vocabulary. A
procedure's steps are authored on this side, and nothing outside knows
what one is.

## One kind of step, and why there were two

A step hands a routine to whatever performs it, and sending a record to a
value is one of those routines rather than a second kind of step.

While setting was a kind, it was the one act nothing could propose. A
proposal cites an operation and supplies parameters, so an agent could put
a scan forward and had no shape at all for putting a move forward. The
kind distinction also reached into the walk, which had to ask what sort of
step it held before it could perform one, and into the engine seam, which
only ever saw half the procedure.

## Why a step declares what it touches, and how a set still derives it

Which devices a routine touches is inside the routine, in the engine, and
what an engine records afterwards describes one invocation rather than the
routine, so there is nothing to derive a device list from either. Nothing
here can know, and a step that let the author leave it unsaid would default
to claiming nothing, which is precisely the undeclared scan a rival writer
corrupts. So a step with an empty claim is refused where it is built.

`driving_nothing` is the exception, and it is a constructor rather than a
permission. Some work happens at another facility: a file moved to a
computing centre, a reconstruction run there. Such a step drives no device
here and there is no honest scope for it, so it says so instead of naming
a fiction. The difference from an omission is that somebody wrote it down,
which is the whole of why it is a separate way in rather than an empty
claim being allowed through the ordinary one.

A claim on nothing conflicts with nothing, so such a step never waits and
never blocks. That is correct and it is also the limit of what it means.
A claim is held for as long as a step runs and no longer, and this work
carries on at another facility after the walk has ended, so there was
never anything here for a scope to protect. `docs/conducting.md` says
where a claim stops.

Setting a record is the one routine whose devices the step itself names,
and `setting` is where that derivation stays. It is a constructor and not a
kind: nothing branches on how a step was built, so a walk performs every
step the same way and the engine seam sees the whole procedure. What it
buys is what deriving always bought, that an author writing a record name
cannot also write a claim disagreeing with it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Self

from conductor.claims import Claim, Scope

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SET_ROUTINE: Final = "set"
"""The routine that sends one record to one value.

A name like any other here. Whichever seam a deployment routes it to is
the one that can write records, and nothing above that seam treats it
differently from a scan.
"""

RECORD_PARAMETER: Final = "record"
VALUE_PARAMETER: Final = "value"
"""What `setting` puts its two values under, and what performs it reads."""


class InvalidProcedureError(ValueError):
    """A procedure or one of its steps could not be built as described."""


@dataclass(frozen=True, slots=True)
class Step:
    """One element of a procedure: a routine, what it is given, what it holds."""

    routine: str
    claim: Claim
    parameters: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))
    drives_nothing: bool = False
    """Whether an empty claim was asked for rather than left behind."""

    def __post_init__(self) -> None:
        if not self.routine.strip():
            raise InvalidProcedureError("a step needs a routine to run")
        if self.drives_nothing and self.claim.scopes:
            raise InvalidProcedureError(
                f"the step running {self.routine!r} says it drives nothing and also "
                "claims something, and nothing here will choose between the two"
            )
        if not self.claim.scopes and not self.drives_nothing:
            raise InvalidProcedureError(
                f"the step running {self.routine!r} must declare what it touches, "
                "because nothing here can derive that from a routine name. A step "
                "whose work happens at another facility is built with driving_nothing"
            )

    @classmethod
    def driving_nothing(cls, routine: str, parameters: Mapping[str, object] | None = None) -> Self:
        """A step whose work happens somewhere this cannot claim.

        Built through its own constructor so that an empty claim is
        something a caller asked for by name. Reaching the same state by
        passing no scopes stays refused, because that is what forgetting
        looks like.
        """
        return cls(
            routine=routine,
            claim=Claim(scopes=frozenset()),
            parameters=MappingProxyType(dict(parameters or {})),
            drives_nothing=True,
        )

    @classmethod
    def setting(cls, record: str, value: float) -> Self:
        """A step that sends one record to one value, holding that record.

        The claim is derived and not taken, so there is nothing for an
        author to get wrong. A field suffix drops out on the way in,
        because a claim on a motor's value and one on its stop field are
        a claim on the same motor twice.
        """
        if not record.strip():
            raise InvalidProcedureError("a set needs a record to write to")
        return cls(
            routine=SET_ROUTINE,
            claim=Claim(scopes=frozenset({Scope.record(record)})),
            parameters=MappingProxyType({RECORD_PARAMETER: record, VALUE_PARAMETER: value}),
        )

    @property
    def describes(self) -> str:
        return f"{self.routine} over {self.claim}"


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
