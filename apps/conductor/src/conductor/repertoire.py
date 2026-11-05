"""Which routines this conductor can be asked for, and what runs each.

A conductor used to install one engine, and that was the whole of what it
could run. Work that crosses a boundary does not fit in one: a procedure
that sets a record at a beamline, hands a scan to an acquisition server
and then asks somewhere else entirely to reconstruct it needs three
things behind one seam, and nothing above the seam should be able to tell.

So this is an engine seam made of several, picking by the routine a step
names. It satisfies the same Protocol the things inside it do, which is
what keeps `conduct` unable to know it is there.

## Why it also answers what this conductor runs

`Tasking.take` is given every routine this conductor can run, and only
work whose every step names one of them comes back. That set and the
table below are the same fact, and they were two before: an entrypoint
built an engine from configuration and then read the routine list out of
the same configuration a second time, in a second function that had to
match the first arm for arm. Two readings of one fact drift, and the
drift here is silent in the worst direction, because a conductor that
overstates what it runs claims work it must then refuse.

## Why a routine belongs to exactly one engine

A table and not a list asked in turn. Order would decide which engine got
a routine two of them offered, and a deployment that names `set` twice
has made a mistake rather than expressed a preference. `of` refuses it
where the table is built, which is startup, rather than letting the
first match win at the first step of the day.

## Why an unknown routine is refused the way an engine refuses one

`RoutineNotRunHereError` and not a `KeyError`. A walk tells that apart
from a fault and reports `Declined`, which says the work reached a
beamline that does not do this thing. A `KeyError` would arrive as
`Broke` and send somebody looking for a broken conductor.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from conductor.seams import RoutineNotRunHereError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from conductor.seams import Citation, Ran, Running


class RoutineClaimedTwiceError(ValueError):
    """Two engines were configured to run one routine.

    Raised where the table is built rather than where a step reaches it,
    because the alternative is a deployment that starts, runs the routine
    through whichever engine happened to be first, and is correct by
    accident until the order changes.
    """

    def __init__(self, routine: str) -> None:
        self.routine = routine
        super().__init__(
            f"two engines are configured to run {routine!r}, and a routine "
            "belongs to one of them. Name it under a single engine."
        )


@runtime_checkable
class Stationed(Protocol):
    """Asking what a routine would actually be driven against.

    Separate from `Running` and optional, because most engines have no
    answer and should not be made to invent one. A transfer engine
    drives a service at another facility, and the honest reply is that
    there is no station here, which is why a step it runs declares that
    it drives no device at all.

    What this exists for is the one disagreement nothing else can see. A
    step names the devices it claims and a deployment names the server
    its engine talks to, and the two are written in different places by
    different people: the first in a procedure that cannot be retired,
    the second in a file on a host. Repoint the second and the first
    still reads the way it always did.

    A claim is a ledger lock rather than a fence on the engine, so
    nothing stops the step. It takes a claim on a namespace nobody is
    serving and drives the one the engine was pointed at, and reports
    success.
    """

    @property
    def station(self) -> str:
        """The namespace a claim driven by this engine would share with it."""
        ...


@runtime_checkable
class Stationing(Protocol):
    """Asking an engine table where a given routine would be driven.

    `Stationed` is the engine's own answer; this is the table's, and the
    two are separate because only the table knows which engine a routine
    reaches. A walk holds the table rather than the engine, so this is
    the one it can ask.
    """

    def station_for(self, routine: str) -> str | None:
        """Where that routine would be driven, or None when there is no such place."""
        ...


@dataclass(frozen=True, slots=True)
class Repertoire:
    """Several engine seams behind one, picked by the routine a step names."""

    engines: Mapping[str, Running]

    @classmethod
    def of(cls, *offers: tuple[frozenset[str], Running]) -> Self:
        """Bind each engine to the routines a deployment said it runs.

        The routines come from configuration rather than from the engine,
        for the reason the configuration gives: a built engine cannot be
        asked what it holds, and a disagreement shows up as that engine
        refusing a routine it was handed, which is loud.
        """
        bound: dict[str, Running] = {}
        for routines, engine in offers:
            for routine in routines:
                if routine in bound:
                    raise RoutineClaimedTwiceError(routine)
                bound[routine] = engine
        return cls(engines=MappingProxyType(bound))

    @property
    def runs(self) -> frozenset[str]:
        """Every routine this conductor can be asked for."""
        return frozenset(self.engines)

    def station_for(self, routine: str) -> str | None:
        """Where that routine would be driven, if the engine behind it has a place.

        None covers both an unknown routine and an engine with nowhere
        to name, and the two want the same answer here: there is nothing
        to compare a claim against. An unknown routine is refused by
        `run` a moment later with a message about the routine, which is
        the complaint worth making.
        """
        engine = self.engines.get(routine)
        return engine.station if isinstance(engine, Stationed) else None

    def run(self, routine: str, parameters: Mapping[str, object], cites: Citation | None) -> Ran:
        """Hand the step to whichever engine runs that routine."""
        engine = self.engines.get(routine)
        if engine is None:
            known = ", ".join(sorted(self.engines)) or "nothing"
            raise RoutineNotRunHereError(
                routine,
                f"this conductor was asked to run {routine!r} and runs {known}",
            )
        return engine.run(routine, parameters, cites)


__all__ = [
    "Repertoire",
    "RoutineClaimedTwiceError",
    "Stationed",
    "Stationing",
]
