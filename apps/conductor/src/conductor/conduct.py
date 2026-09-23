"""Walk a procedure, holding each step's claim for exactly as long as it runs.

The walk is sequential and stops at the first step that does not finish.
Both of those are decisions rather than defaults.

**Sequential**, because a conductor that interleaved steps would be the
thing creating the hazard it exists to prevent, and nothing has asked for
parallelism. When something does, the ledger is already the mechanism: two
steps may run at once exactly when their claims do not overlap.

**Stops**, because a step that was refused or that broke leaves the
beamline in a state this system did not plan for, and the next step was
written on the assumption that the one before it worked. Carrying on would
be guessing. The steps not reached are reported as `Skipped` rather than
omitted, so a reader of the tally can see the whole procedure and where it
stopped.

## What a walk reports as it goes

Outcomes reach the recording seam one at a time, as each step ends,
rather than in the tally at the bottom. The tally is built on the last
line, so a process that dies before reaching it leaves nothing at all,
not even the steps that finished. Reporting on the way through is what
makes those steps survive the walk.

Every outcome goes out, `Skipped` included. Whether a run of skips is
worth a call each is a question about a particular way of recording,
and answering it here would put one deployment's cost model in the
loop that every deployment shares.

## What a walk does not do

It does not stop the hardware when it ends. `spikes/conductor/FINDINGS.md`
killed a driver mid-move and watched the motor travel to its target with
nothing alive that had asked for it, and a SIGKILL offers no hook at all.
So a conductor cannot promise that dying stops anything, and this module
does not pretend to: anything that must stop on abandonment needs a
watchdog beside the hardware, which is neither this nor AROC. What
reporting buys is narrower and worth stating exactly: the record of a
walk can survive the walk. The walk cannot.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from conductor.claims import ClaimConflictError, Ledger
from conductor.outcomes import Broke, Done, Outcome, Refused, Skipped
from conductor.procedure import Acquire, Move, Procedure
from conductor.seams import ReferenceNotCarriedError

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from conductor.procedure import Step
    from conductor.seams import Acquisition, Control, Recording


@dataclass(frozen=True, slots=True)
class Walk:
    """What one pass over a procedure came to.

    `reference` is this walk's own name, the one every report about it
    carried. A caller holding it can ask whatever was recording where
    the walk got to, which is the only way to find out once the object
    below has gone with the process that held it.
    """

    procedure: str
    reference: str
    outcomes: Sequence[Outcome]

    @property
    def finished(self) -> bool:
        """Whether every step ran without being refused or breaking."""
        return all(isinstance(outcome, Done) for outcome in self.outcomes)

    def tally(self) -> dict[str, int]:
        """How many of each outcome, for printing at the end of a session."""
        counted: dict[str, int] = {}
        for outcome in self.outcomes:
            name = type(outcome).__name__
            counted[name] = counted.get(name, 0) + 1
        return counted


class _RecordsNothing:
    """The recording seam a walk gets when its caller named none.

    A walk with this one promises nothing about surviving itself, which
    is the right promise for a procedure somebody is watching run from a
    terminal. It is an object rather than three `if` statements so that
    the loop below reads the same either way.
    """

    def walk_began(self, reference: str, procedure: str, steps: Sequence[str]) -> None:
        """Say nothing."""

    def step_ended(self, reference: str, index: int, outcome: Outcome) -> None:
        """Say nothing."""

    def walk_ended(self, reference: str) -> None:
        """Say nothing."""


def conduct(
    procedure: Procedure,
    *,
    control: Control,
    acquisition: Acquisition,
    ledger: Ledger | None = None,
    recording: Recording | None = None,
    mint: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> Walk:
    """Walk a procedure across the seams, one claim at a time, reporting as it goes.

    `ledger` is taken rather than made so that two walks in one process
    share one, which is what makes a claim mean anything between them. A
    walk given none gets its own, which is right for a single procedure
    and wrong the moment there are two.

    `recording` is where each outcome goes as it happens. A walk given
    none still returns everything it did; it just leaves nothing behind
    if it does not get to the end.

    `mint` is the source of both this conductor's names: the walk's own
    reference and the one each acquisition carries into the engine's
    record. One minter rather than two, because both answer the same
    question: what this conductor calls something nothing else has named
    yet. It is a parameter because a test needs to know what it will be.
    """
    book = ledger if ledger is not None else Ledger()
    told = recording if recording is not None else _RecordsNothing()
    reference = mint()

    described = [step.describes for step in procedure.steps]
    told.walk_began(reference, procedure.name, tuple(described))

    outcomes: list[Outcome] = []
    stopped = False

    for index, step in enumerate(procedure.steps):
        if stopped:
            outcome: Outcome = Skipped(step=described[index])
        else:
            outcome = _attempt(
                step,
                described=described[index],
                holder=f"{procedure.name}[{index}]",
                book=book,
                control=control,
                acquisition=acquisition,
                mint=mint,
            )
            stopped = not isinstance(outcome, Done)

        outcomes.append(outcome)
        told.step_ended(reference, index, outcome)

    told.walk_ended(reference)
    return Walk(procedure=procedure.name, reference=reference, outcomes=tuple(outcomes))


def _attempt(
    step: Step,
    *,
    described: str,
    holder: str,
    book: Ledger,
    control: Control,
    acquisition: Acquisition,
    mint: Callable[[], str],
) -> Outcome:
    """Run one step under its claim and turn whatever happened into a word.

    Split out of the loop so that reporting an outcome sits outside it.
    A recording seam that raised inside this `except Exception` would be
    recorded as the step having broken, which is a lie about the step:
    the move arrived and only the telling failed.
    """
    try:
        with book.granted(holder, step.claim):
            return _perform(step, described, control, acquisition, mint)
    except ClaimConflictError as conflict:
        return Refused(step=described, holder=conflict.holder, overlap=conflict.overlap)
    except Exception as exc:
        return Broke(step=described, cause=f"{type(exc).__name__}: {exc}")


def _perform(
    step: Step,
    described: str,
    control: Control,
    acquisition: Acquisition,
    mint: Callable[[], str],
) -> Outcome:
    """Run one step through whichever seam it belongs to."""
    match step:
        case Move(record=record, to=to):
            control.move(record, to)
            return Done(step=described)
        case Acquire(plan=plan, parameters=parameters):
            reference = mint()
            acquired = acquisition.acquire(plan, parameters, reference)
            if acquired.reference != reference:
                raise ReferenceNotCarriedError(plan=plan, asked=reference, got=acquired.reference)
            return Done(step=described, acquired=acquired)
