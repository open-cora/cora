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

## What a walk does not do

It does not stop the hardware when it ends. `spikes/conductor/FINDINGS.md`
killed a driver mid-move and watched the motor travel to its target with
nothing alive that had asked for it, and a SIGKILL offers no hook at all.
So a conductor cannot promise that dying stops anything, and this module
does not pretend to: anything that must stop on abandonment needs a
watchdog beside the hardware, which is neither this nor AROC.
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
    from conductor.seams import Acquisition, Control


@dataclass(frozen=True, slots=True)
class Walk:
    """What one pass over a procedure came to."""

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


def conduct(
    procedure: Procedure,
    *,
    control: Control,
    acquisition: Acquisition,
    ledger: Ledger | None = None,
    mint: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> Walk:
    """Walk a procedure across the two seams, one claim at a time.

    `ledger` is taken rather than made so that two walks in one process
    share one, which is what makes a claim mean anything between them. A
    walk given none gets its own, which is right for a single procedure
    and wrong the moment there are two.

    `mint` is the source of the reference an acquisition carries. It is a
    parameter because a test needs to know what it will be, and because
    the identity is this conductor's to choose: an engine hands a caller
    nothing at submit time, and carries what it is given.
    """
    book = ledger if ledger is not None else Ledger()
    outcomes: list[Outcome] = []
    stopped = False

    for index, step in enumerate(procedure.steps):
        holder = f"{procedure.name}[{index}]"
        described = step.describes

        if stopped:
            outcomes.append(Skipped(step=described))
            continue

        try:
            with book.granted(holder, step.claim):
                outcomes.append(_perform(step, described, control, acquisition, mint))
        except ClaimConflictError as conflict:
            outcomes.append(
                Refused(step=described, holder=conflict.holder, overlap=conflict.overlap)
            )
            stopped = True
        except Exception as exc:
            outcomes.append(Broke(step=described, cause=f"{type(exc).__name__}: {exc}"))
            stopped = True

    return Walk(procedure=procedure.name, outcomes=tuple(outcomes))


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
