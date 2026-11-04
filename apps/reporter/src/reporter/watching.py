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

## Two seams, because there are two far sides

`Tracking` is the record, asked what it is still owed an account of.
`Watching` is whatever is holding the work, asked how one piece of it
turned out. They are separate for the reason every seam here is: they
are two capabilities, answered by two different systems, and an
implementation of one has no business holding a client for the other.

The first of them was going to be unnecessary. A driver writes the two
ids into the label it submits work under, so a watcher could in
principle ask a service what it is holding and read each piece of work's
own label, needing no record at all. That works for a transfer service
and is impossible for the compute service this facility runs, whose
client can ask about a task id and cannot list one. So the references
come from the record, which holds them for both and is authoritative
about which are unaccounted for.

The label is still what makes a task legible to a person reading the
service's own console, and `read_label` is still how a reference found
there is traced back. It is no longer how the work is found.

## Why a reference alone does not say who holds it

A task id is a bare identifier and the record does not say which service
it was given to, because at the time it was recorded only the engine
knew. So an implementation of `Watching` that does not recognise a
reference raises `UnknownWorkError` rather than answering, and `across`
asks each of several in turn until one does.

That is a workaround for something the record could say and does not.
Carrying the service on the handoff would make this a lookup rather than
a search, and it is worth doing the day a third service appears.

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


class UnknownWorkError(LookupError):
    """A reference the thing asked does not recognise.

    Not a fault on its own. A facility running more than one service
    gives each a reference the others have never heard of, so this is
    the ordinary answer from all but one of them.
    """

    def __init__(self, reference: str) -> None:
        self.reference = reference
        super().__init__(f"nothing asked recognises {reference!r}")


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
class Tracking(Protocol):
    """Asking the record what it is still owed an account of."""

    def handovers(self) -> Sequence[Handover]:
        """Every step whose work outlived its walk and has no ending yet."""
        ...


@runtime_checkable
class Watching(Protocol):
    """Asking whoever holds a piece of work how it turned out.

    One method, written out rather than imported, so this package gains
    no dependency on any service and can be read and tested without one.
    """

    def ending(self, reference: str) -> Ending | None:
        """How that work turned out, or nothing while it is still going.

        Raises `UnknownWorkError` for a reference this does not
        recognise, which is how `across` finds out it asked the wrong
        one rather than reading a stranger's answer as this work's.
        """
        ...


@dataclass(frozen=True, slots=True)
class across:  # noqa: N801
    """Several far sides behind one, asked in turn until one knows the work.

    Lowercase because it reads as the preposition it is at the call
    site, and because what it builds is a `Watching` rather than a thing
    of its own: it satisfies that Protocol and nothing above it can tell
    it is there. `conductor.repertoire` makes the same move for engines,
    for the same reason.

    Order is not a preference. A reference belongs to exactly one
    service and the others do not recognise it, so whichever answers is
    the right one and asking them in a different order gives the same
    result.
    """

    watchers: tuple[Watching, ...]

    def ending(self, reference: str) -> Ending | None:
        for watcher in self.watchers:
            try:
                return watcher.ending(reference)
            except UnknownWorkError:
                continue
        raise UnknownWorkError(reference)


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
    "Tracking",
    "UnknownWorkError",
    "UnreadableLabelError",
    "WatchOutcome",
    "Watching",
    "across",
    "read_label",
    "resolve",
]
