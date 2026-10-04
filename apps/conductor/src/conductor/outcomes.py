"""One word per step, and the tally a walk comes back with.

Distinct classes rather than one record carrying a verdict string, which
is the move `apps/keeper` makes throughout for the same reason: a field can
be set wrong and a class cannot, and the thing reading a tally keys off
the class rather than parsing a word.

Five classes and four words. `Refused` and `Declined` both travel as
the one word the keeper has for a step that did not start, and they are
kept apart here because an operator does different things about them.
Collapsing them would be putting a deployment's question into the only
field a reader of this process has.

The vocabulary is deliberately small and none of it says whether the
science worked. `Done` means the seam returned without raising. That is not
the same as the step having done what it meant to: a scan whose data was
corrupted can still come back `success`. A word here implying otherwise would be the same
overclaim `apps/keeper` refused when it picked `reported` over `witnessed`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conductor.claims import Scope
    from conductor.seams import Ran


@dataclass(frozen=True, slots=True)
class Done:
    """The step ran and the seam returned. Says nothing about the result."""

    step: str
    ran: Ran | None = None


@dataclass(frozen=True, slots=True)
class Refused:
    """A claim conflict stopped the step before it touched anything.

    The only outcome here that is unambiguously good news when it
    happens: nothing was touched, and the hold did what it is for.

    It does not happen under the daemon this package ships. That walks
    one procedure at a time on one thread, and every step gives its
    claim back before the next one asks, so no step of its can meet a
    holder. What reaches this is a process embedding a walk beside
    something else holding the same ledger, which is also how the tests
    reach it: by taking a hold before the walk starts.
    """

    step: str
    holder: str
    overlap: frozenset[Scope]


@dataclass(frozen=True, slots=True)
class Declined:
    """The engine does not run what the step asked for.

    Apart from `Refused`, which is a claim this walk lost, because the
    two clear differently: a conflict clears when the other walk ends,
    and this does not clear until a deployment changes or the work goes
    to a beamline that does the thing.

    Apart from `Broke`, which is what this was until the walk learned to
    tell them apart. An engine never given a routine has not failed at
    anything, and filing it as a fault sends somebody to a healthy
    beamline.
    """

    step: str
    routine: str
    cause: str


@dataclass(frozen=True, slots=True)
class Broke:
    """The seam raised. The exception is kept as text, not re-raised."""

    step: str
    cause: str


@dataclass(frozen=True, slots=True)
class Skipped:
    """The walk had already stopped before reaching this step."""

    step: str


Outcome = Done | Refused | Declined | Broke | Skipped
