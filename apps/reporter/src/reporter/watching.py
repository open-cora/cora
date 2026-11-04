"""Finding work that outlived the walk that started it, and finishing its record.

Some work a step hands over finishes while the thing that asked is still
waiting, and some does not. A file transfer runs for hours and a
reconstruction for longer, so the driver stops waiting, records the far
side's name for the work, and ends. The record then says a step was
handed off and nothing more, which is true and is not the end of the
story.

This is the part that goes back and asks. It is a reporter rather than a
driver because of what it writes: `Reporting` records what an engine did
to a step's run, and that is exactly the account a finished transfer or
reconstruction owes. A driver reports what its walk did, which it
already did when it handed the work over.

## Why nothing is looked up

`intents.ReportStepRun` is explicit that the two ids come from the
engine's own metadata, where whatever dispatched the work put them, and
are not resolved or guessed. For work handed to a service rather than to
a record, that metadata is the label the work was submitted under.

So this does not ask the keeper which steps are unfinished. It asks the
service what it is holding, reads each piece of work's own label, and
reports against the step the label names. The record is what gets
written, not what gets searched, and a watcher that had to search would
be inventing a join the work already carries.

The cost is honest: work submitted without a label cannot be resolved
this way, and a driver given no citation submits none. That is the same
rule everywhere here, which is that an adapter with no ids writes none
rather than inventing them, and the consequence is visible rather than
silent.

## Why a start is reported here and not by the driver

The keeper will not take a completion for a run it was never told
began, and the driver cannot be the one to say so. Its reporting seam
says how a step ended and that a walk is over, and carries nothing
about engine runs, deliberately, because a walk reports what it did
rather than what its engine said. Whatever watches the engine sends the
engine's account, and for this work that is this.

So a resolution is two reports, a start and an ending, and they are both
genuinely this watcher's to make. A start that the record already holds
comes back as `DisagreedError`, which is read here as already known
rather than as a fault: a watcher that ran twice over one task must
write the same record as one that ran once.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable
from uuid import UUID

from reporter.intents import ReportStepRun
from reporter.seams import DisagreedError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from reporter.intents import Report
    from reporter.seams import Reporting

LABEL_PREFIX: Final = "cora"
"""What marks a piece of work as this system's, in a service shared with others.

A word and not a flag, because a label is the only field most services
let a submitter choose freely. Anything not beginning with it belongs to
somebody else at this facility and is left alone.
"""

LABEL_PARTS: Final = 3
"""The prefix and the two ids, which is the whole of what a label carries."""


class UnreadableLabelError(ValueError):
    """A label that does not name a step this can report against."""


@dataclass(frozen=True, slots=True)
class Handover:
    """One piece of work a far side holds, and the step it belongs to."""

    reference: str
    execution_id: UUID
    step_id: UUID


@dataclass(frozen=True, slots=True)
class Ending:
    """How work a far side was given turned out, and why.

    `detail` is why, empty when there is nothing to add.

    It does not reach the keeper, and that is a limitation rather than a
    choice: `ReportStepRun` carries the verb and the reference and has
    nowhere to put a reason. So the record will say a run failed and not
    why, and this field exists so that whatever runs this can say it in
    a log. A transfer refused for a missing file and one refused for a
    permission are different problems with different fixes, and a
    watcher that knew which and said nothing anywhere would be worse
    than one that cannot write it down.
    """

    report: Report
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Resolved:
    """The work ended and the record now says how."""

    reference: str
    report: Report


@dataclass(frozen=True, slots=True)
class StillGoing:
    """The work has not ended, so there is nothing to say yet."""

    reference: str


@dataclass(frozen=True, slots=True)
class AlreadyTold:
    """The record was already past this, so nothing was written.

    The ordinary outcome of a second pass over the same task, and not a
    fault. A watcher is not the only thing that may have reported, and
    two watchers racing is a thing the record settles rather than a
    thing to prevent.
    """

    reference: str


WatchOutcome = Resolved | StillGoing | AlreadyTold


@runtime_checkable
class Watching(Protocol):
    """What a far side is holding, and how one piece of it turned out.

    Two methods, written out rather than imported, so this package gains
    no dependency on any service and can be read and tested without one.
    """

    def handovers(self) -> Sequence[Handover]:
        """Every piece of this system's work the far side still knows about."""
        ...

    def ending(self, reference: str) -> Ending | None:
        """How that work turned out, or nothing while it is still going."""
        ...


def read_label(label: str, reference: str) -> Handover:
    """The step a piece of work belongs to, read off its own label.

    Strict on purpose. A label that nearly parses is a label somebody
    else wrote, and reporting against ids guessed from one would write
    another execution's record.
    """
    parts = label.split()
    if len(parts) != LABEL_PARTS or parts[0] != LABEL_PREFIX:
        raise UnreadableLabelError(f"{label!r} does not name a step this system dispatched")
    try:
        return Handover(
            reference=reference,
            execution_id=UUID(parts[1]),
            step_id=UUID(parts[2]),
        )
    except ValueError as malformed:
        raise UnreadableLabelError(f"{label!r} carries something that is not an id") from malformed


def resolve(
    watching: Watching,
    reporting: Reporting,
    handover: Handover,
    *,
    origin: str,
    occurred_at: datetime | None = None,
) -> WatchOutcome:
    """Ask after one handover, and write what the record is missing.

    The start goes first because the keeper will not take an ending for
    a run it was never told began. Both may already be known, and both
    read that the same way.
    """
    ending = watching.ending(handover.reference)
    if ending is None:
        return StillGoing(reference=handover.reference)

    known = _tell(reporting, handover, "Started", origin, occurred_at)
    settled = _tell(reporting, handover, ending.report, origin, occurred_at)
    if known and settled:
        return AlreadyTold(reference=handover.reference)
    return Resolved(reference=handover.reference, report=ending.report)


def _tell(
    reporting: Reporting,
    handover: Handover,
    report: Report,
    origin: str,
    occurred_at: datetime | None,
) -> bool:
    """Send one report, and say whether the record already held it."""
    try:
        reporting.record(
            ReportStepRun(
                execution_id=handover.execution_id,
                step_id=handover.step_id,
                reported=report,
                engine_reference=handover.reference,
                occurred_at=occurred_at,
                origin=origin,
            )
        )
    except DisagreedError:
        return True
    return False


__all__ = [
    "AlreadyTold",
    "Ending",
    "Handover",
    "Resolved",
    "StillGoing",
    "UnreadableLabelError",
    "WatchOutcome",
    "Watching",
    "read_label",
    "resolve",
]
