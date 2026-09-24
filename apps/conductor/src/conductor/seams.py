"""The three outward seams, named by what they do rather than by a product.

A seam is a Protocol here and an adapter somewhere else, so which control
library and which acquisition engine a deployment runs is a choice it
makes at its entrypoint. That is the same arrangement `apps/reporter` uses
for a store, and the reason is the same: a beamline runs what it runs, and
a package that named one would be holding an opinion a deployment owns.

None of the Protocols carries a `Port` suffix. Everything in this module is a
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

## Why recording is a seam and not a call

Two of these seams make something happen and the third makes something
known. Saying it out loud would be easier than routing it through a
Protocol, and it is routed anyway, because the core of this package
imports the standard library and itself and a test holds it there. The
client with the most reason to reach out directly is the one that can
least afford to.

It also leaves the degraded case where it belongs. Whether a walk may
carry on while nothing can be told about it is a question about which
adapter a deployment installs, and an adapter that means to carry on
handles its own outage. Nothing in `conduct` catches a recording
failure, so an adapter that raises stops the walk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from conductor.outcomes import Outcome


@dataclass(frozen=True, slots=True)
class Acquired:
    """What came back from asking an engine to run something.

    `engine_reference` is the name that joins. A reporter watching the
    same engine records its runs under the engine's own name for them, so
    that is what AROC can be asked for later, and
    `docs/reference/client-contract.md` holds both halves of that
    agreement. It is optional because not every engine has a name to
    give, and because a plan that opened no run has nothing to be named.

    `reference` is this conductor's own, minted before the request went
    out and carried into the engine's record: a bare RunEngine hands a
    caller nothing at submit time but copies metadata it is given
    verbatim into the start document. It is not the join. It puts this
    conductor's name on the engine's own permanent record, where a person
    reading a data catalogue can find it, and an adapter that reads it
    back out is what gives the check below something real to compare.
    """

    reference: str
    engine_reference: str | None
    said: str


class ReferenceNotCarriedError(RuntimeError):
    """An engine answered naming a reference other than the one it was given.

    An adapter is expected to read this field back out of what the engine
    recorded rather than echo the argument it was handed, so a mismatch
    means the engine dropped the name on the way through. That matters
    even though the join runs on `engine_reference`: an engine that
    silently discards metadata is one whose record of what ran here is
    wrong, and the walk would report `Done` for every step regardless,
    which is the shape of failure this package exists to refuse. It costs
    one comparison to catch here and cannot be caught at all afterwards.
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


@runtime_checkable
class Recording(Protocol):
    """Telling something outside what a walk is doing, while it does it.

    Every method is named for what already happened, because none of
    them asks for anything. A walk reports; it does not consult.

    ## This shape predates the dispatch, and all three signatures show it

    **Nothing implements this, and `walk_began` is wrong in every part
    of it.** It was written when a walk opened its own record. AROC now
    composes the procedure and dispatches the execution before anything
    is asked to drive it, which removes the reason for each argument:

        reference   the caller minted a name because there was no
                    handle at the moment a walk started. There is one
                    now, and it is the execution's id.
        procedure   AROC holds the procedure. Sending its name back
                    tells the record something it wrote.
        steps       likewise. The step list rides the execution's
                    genesis, and the ids on it are what a report has
                    to name.

    The argument the step list was carrying is the one part that
    survives: a walk that dies mid-flight stops reporting, and whatever
    holds the record is then looking at a prefix. AROC closes that by
    holding the whole list from the dispatch, rather than by being told
    it at the start.

    What replaces this is a claim and a report against a record that
    already exists, which is the conductor's work intake, and that is
    the largest unbuilt piece here. The Protocol is left standing rather
    than half-corrected because the correction is that intake's to make.
    `docs/reference/conducting.md` says the same.
    """

    def walk_began(self, reference: str, procedure: str, steps: Sequence[str]) -> None:
        """A walk started, over these steps, in this order."""
        ...

    def step_ended(self, reference: str, index: int, outcome: Outcome) -> None:
        """One step came to an end, whichever way it ended."""
        ...

    def walk_ended(self, reference: str) -> None:
        """The walk is over, and nothing further will be reported under it."""
        ...
