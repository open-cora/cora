"""The two outward seams, named by what they do rather than by a product.

A seam is a Protocol here and an adapter somewhere else, so which control
library and which acquisition engine a deployment runs is a choice it
makes at its entrypoint. That is the same arrangement `apps/reporter` uses
for a store, and the reason is the same: a beamline runs what it runs, and
a package that named one would be holding an opinion a deployment owns.

Neither Protocol carries a `Port` suffix. Everything in this module is a
seam, so saying so distinguishes nothing, and `apps/api` forbids the
suffix for that reason.

## Why acquisition returns what the engine said, unmapped

`spikes/conductor/FINDINGS.md` drove four collisions into a real scan and
every one of them ended `exit_status: "success"`, including a six-point
scan that took four of its readings at one position. So an engine's word
for how a run ended is a claim this system was given, not a fact it
checked, and a seam that turned `success` into a boolean here would be
laundering the claim into a conclusion one layer before anyone could see
it. The word travels verbatim and something further out decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class Acquired:
    """What came back from asking an engine to run something.

    `reference` is this conductor's own, minted before the request went
    out, which is what makes the run findable afterwards: a bare
    RunEngine hands a caller nothing at submit time but carries metadata
    it is given verbatim into the start document. `engine_reference` is
    the engine's own name for the run, when it says one, and it is
    optional because not every engine has one to give.
    """

    reference: str
    engine_reference: str | None
    said: str


class ReferenceNotCarriedError(RuntimeError):
    """An engine answered naming a reference other than the one it was given.

    The join between a run caused here and a run recorded elsewhere is
    the minted reference and nothing else. An adapter that put its own
    identifier in that field would break every later lookup while the
    walk reported `Done` for every step, which is the shape of failure
    this package exists to refuse. It costs one comparison to catch here
    and cannot be caught at all afterwards.
    """

    def __init__(self, *, plan: str, asked: str, got: str) -> None:
        self.plan = plan
        self.asked = asked
        self.got = got
        super().__init__(
            f"the acquisition of {plan!r} was given the reference {asked!r} "
            f"and came back with {got!r}, so nothing could find the run later"
        )


@runtime_checkable
class Control(Protocol):
    """Reading and writing one record at a time, underneath any engine."""

    def move(self, record: str, value: float) -> None:
        """Send a record to a value and return when it is there."""
        ...

    def read(self, record: str) -> float:
        """Read a record now."""
        ...


@runtime_checkable
class Acquisition(Protocol):
    """Asking an engine to run a routine, and hearing how it went."""

    def acquire(self, plan: str, parameters: Mapping[str, object], reference: str) -> Acquired:
        """Run a plan, carrying `reference` so the run can be found later."""
        ...
