"""The record's words for how a step ended, and the one judgement on them.

Shared by every profile in this directory, because each of them has to
decide the same first question before it decides anything of its own:
did this go wrong. A profile that answered that differently from its
neighbour would not be a different strategy, it would be a bug in one of
them.

## Why the words are spelled here

They arrive as the record's own strings, carried through without being
interpreted, and this directory is the first thing on this side that
interprets them. Nothing in `thinker` holds a list of them to import,
and importing the keeper is not available to a client that ships as its
own repository. So they are literals, and they are compared against the
keeper's own enumerations by a check in the development tree that holds
both repositories, because a word nothing compares is a rename away from
a table that quietly stops matching.

That check cannot live here. This repository ships without the keeper
beside it, so the comparison is only possible where both are, which is
the same reason the words are literals in the first place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from thinker.case import Step

DONE: Final = "Done"
"""The keeper's word for a step whose driver returned."""

BROKEN: Final = "Broken"
"""The keeper's word for a step whose driver raised."""

ABORTED: Final = "Aborted"
FAILED: Final = "Failed"

ENGINE_FAULTS: Final[frozenset[str]] = frozenset({ABORTED, FAILED})
"""The engine's own terminal words for a run that did not finish well.

The engine's third terminal word, for a run that finished, is absent on
purpose. So is the empty state a step that opened no run carries, and
reading that as a fault would refer every procedure that only sets
records.
"""


def faulted(step: Step) -> bool:
    """Whether either observer said this step went wrong.

    Either, not both. The record keeps two claims about how a step ended
    and refuses to collapse them, because they can disagree and neither
    is checkable from here. A run whose seam returned cleanly and whose
    engine then failed is reported done with an engine state of failed,
    so reading only the driver's word calls that run clean.
    """
    became = step.became
    if became is None:
        return False
    return became.reported == BROKEN or became.engine_state in ENGINE_FAULTS


def ended_badly(step: Step) -> str:
    """How one step ended, in whichever words the record used.

    Both when they disagree, because that disagreement is the reason a
    reader is being sent to the record.
    """
    became = step.became
    if became is None:
        return "never reported"
    if became.engine_state is None:
        return became.reported
    return f"{became.reported} with an engine that {became.engine_state}"


__all__ = ["ABORTED", "BROKEN", "DONE", "ENGINE_FAULTS", "FAILED", "ended_badly", "faulted"]
