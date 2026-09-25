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

It does not stop the hardware when it ends. A spike
killed a driver mid-move and watched the motor travel to its target with
nothing alive that had asked for it, and a SIGKILL offers no hook at all.
So a conductor cannot promise that dying stops anything, and this module
does not pretend to: anything that must stop on abandonment needs a
watchdog beside the hardware, which is neither this nor AROC. What
reporting buys is narrower and worth stating exactly: the record of a
walk can survive the walk. The walk cannot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from conductor.claims import ClaimConflictError, Ledger
from conductor.outcomes import Broke, Done, Outcome, Refused, Skipped
from conductor.procedure import Acquire, Move, Procedure
from conductor.seams import ReferenceNotCarriedError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from conductor.procedure import Step
    from conductor.seams import Acquisition, Aroc, Citation, Control, Reporting


@dataclass(frozen=True, slots=True)
class Walk:
    """What one pass over a procedure came to.

    It has no name of its own. It had one, minted at the top of the walk
    and carried into each engine's record, and that existed because
    nothing else identified the work: a walk opened its own record, so
    the only identity available was one it made up. AROC dispatches an
    execution now, and the id of that execution is what everything
    reporting on this walk already uses. A second name beside it would be
    one nothing else in the system knows.

    A caller wanting to know where a walk got to after the process
    holding this has gone asks AROC for the execution, which is where
    every outcome went as it happened.
    """

    procedure: str
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


@dataclass(frozen=True, slots=True)
class _BoundToOneExecution:
    """An `Aroc` seam and the execution a walk is reporting against.

    The adapter half of `Reporting`, and the only place the execution id
    is remembered. Everything below it takes an index and nothing takes
    an id, which is what keeps `conduct` from being able to report
    against the wrong record.
    """

    aroc: Aroc
    execution_id: str

    def step_ended(self, index: int, outcome: Outcome) -> None:
        self.aroc.report(self.execution_id, index, outcome)

    def walk_ended(self) -> None:
        self.aroc.finish(self.execution_id)


def reports_to(aroc: Aroc, execution_id: str) -> Reporting:
    """Bind a seam to one execution, for handing to `conduct`.

    A function rather than a class a caller instantiates, because what
    it returns is a `Reporting` and the concrete type is nobody's
    business. It lives here rather than in `seams` for the reason that
    module gives: `seams` holds Protocols, and this is the one place
    that turns one into the other.
    """
    return _BoundToOneExecution(aroc=aroc, execution_id=execution_id)


class _RecordsNothing:
    """What a walk reports through when its caller named nowhere.

    A walk with this one promises nothing about surviving itself, which
    is the right promise for a procedure somebody is watching run from a
    terminal. It is an object rather than two `if` statements so that
    the loop below reads the same either way.

    It had a third method once. `walk_began` went when AROC started
    composing the work: a walk no longer opens its record, it is handed
    one that already exists.
    """

    def step_ended(self, index: int, outcome: Outcome) -> None:
        """Say nothing."""

    def walk_ended(self) -> None:
        """Say nothing."""


def conduct(
    procedure: Procedure,
    *,
    control: Control,
    acquisition: Acquisition,
    ledger: Ledger | None = None,
    reporting: Reporting | None = None,
    cites: Sequence[Citation] | None = None,
) -> Walk:
    """Walk a procedure across the seams, one claim at a time, reporting as it goes.

    `ledger` is taken rather than made so that two walks in one process
    share one, which is what makes a claim mean anything between them. A
    walk given none gets its own, which is right for a single procedure
    and wrong the moment there are two.

    `reporting` is where each outcome goes as it happens, bound to the
    execution AROC dispatched. A walk given none still returns
    everything it did; it just leaves nothing behind if it does not get
    to the end, which is the right shape for a procedure somebody is
    running from a terminal.

    It does not announce itself before the first step. It used to, and
    the three things it announced are all things AROC writes before
    anything is asked to drive them.

    `cites` is AROC's ids for these steps, one per step and in their
    order, which each acquisition carries into the engine's own record.
    A walk given none writes no AROC keys, which is what a procedure run
    from a terminal should do: whatever watches that engine then sees a
    hand-run scan, because that is what it was.

    A `cites` of the wrong length is refused rather than zipped to the
    shorter of the two. The failure it would otherwise cause is a run
    filed against the wrong step of the right execution, which reads as
    a plausible record and is detectable by nobody.
    """
    if cites is not None and len(cites) != len(procedure.steps):
        raise ValueError(
            f"the procedure {procedure.name!r} has {len(procedure.steps)} steps and was "
            f"given {len(cites)} citations, so nothing could say which step is which"
        )

    book = ledger if ledger is not None else Ledger()
    told: Reporting = reporting if reporting is not None else _RecordsNothing()

    described = [step.describes for step in procedure.steps]

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
                cites=None if cites is None else cites[index],
            )
            stopped = not isinstance(outcome, Done)

        outcomes.append(outcome)
        told.step_ended(index, outcome)

    told.walk_ended()
    return Walk(procedure=procedure.name, outcomes=tuple(outcomes))


def _attempt(
    step: Step,
    *,
    described: str,
    holder: str,
    book: Ledger,
    control: Control,
    acquisition: Acquisition,
    cites: Citation | None,
) -> Outcome:
    """Run one step under its claim and turn whatever happened into a word.

    Split out of the loop so that reporting an outcome sits outside it.
    A recording seam that raised inside this `except Exception` would be
    recorded as the step having broken, which is a lie about the step:
    the move arrived and only the telling failed.
    """
    try:
        with book.granted(holder, step.claim):
            return _perform(step, described, control, acquisition, cites)
    except ClaimConflictError as conflict:
        return Refused(step=described, holder=conflict.holder, overlap=conflict.overlap)
    except Exception as exc:
        return Broke(step=described, cause=f"{type(exc).__name__}: {exc}")


def _perform(
    step: Step,
    described: str,
    control: Control,
    acquisition: Acquisition,
    cites: Citation | None,
) -> Outcome:
    """Run one step through whichever seam it belongs to."""
    match step:
        case Move(record=record, to=to):
            control.move(record, to)
            return Done(step=described)
        case Acquire(plan=plan, parameters=parameters):
            acquired = acquisition.acquire(plan, parameters, cites)
            if acquired.cites != cites:
                raise ReferenceNotCarriedError(plan=plan, asked=cites, got=acquired.cites)
            return Done(step=described, acquired=acquired)
