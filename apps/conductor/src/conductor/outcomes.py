"""One word per step, and the tally a walk comes back with.

Distinct classes rather than one record carrying a verdict string, which
is the move `apps/api` makes throughout for the same reason: a field can
be set wrong and a class cannot, and the thing reading a tally keys off
the class rather than parsing a word.

The vocabulary is deliberately small and none of it says whether the
science worked. `Done` means the seam returned without raising. The
findings are unambiguous that this is not the same as the step having
done what it meant to: every corrupted scan measured there came back
`success`. A word here that implied otherwise would be the same
overclaim `apps/api` refused when it picked `reported` over `witnessed`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conductor.claims import Scope
    from conductor.seams import Acquired


@dataclass(frozen=True, slots=True)
class Done:
    """The step ran and the seam returned. Says nothing about the result."""

    step: str
    acquired: Acquired | None = None


@dataclass(frozen=True, slots=True)
class Refused:
    """A claim conflict stopped the step before it touched anything.

    The only outcome here that is unambiguously good news: the conductor
    is doing the one job the findings say it exists for.
    """

    step: str
    holder: str
    overlap: frozenset[Scope]


@dataclass(frozen=True, slots=True)
class Broke:
    """The seam raised. The exception is kept as text, not re-raised."""

    step: str
    cause: str


@dataclass(frozen=True, slots=True)
class Skipped:
    """The walk had already stopped before reaching this step."""

    step: str


Outcome = Done | Refused | Broke | Skipped
