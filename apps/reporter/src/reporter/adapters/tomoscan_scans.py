"""Asking a TomoScan server how a scan it was given turned out.

The third far side, and the one that is not a service with a queue. A
transfer or a reconstruction is handed to something that mints an id and
remembers it; TomoScan is a state machine published as records, holding
the scan it is running and nothing else.

That difference is the whole of this module. There is no handle to quote
back, so the driver builds a reference out of what does identify a scan,
and this takes it apart again.

## Why the keeper's two ids are in the reference

The records say what is happening now. A watcher that knew only the
prefix would read them, find a scan, and report on it in perfect good
faith, and once the next scan had started that would be a stranger's
scan reported as this step's. Carrying the ids lets this compare what it
finds against what it was asked about.

The driving side writes the same two ids into the server before it
starts, which is what makes the comparison possible. Where the
reference is built is not this repository and cannot be imported from
here, so the format is spelled out a second time there, and the
development tree the two are written in holds the only rule that
compares them.

## What this cannot answer, stated rather than discovered

A scan whose ids are no longer in the records. TomoScan runs one scan at
a time, so a later one means ours is over, and the records no longer
hold anything about how it went. There is no history to read and no
third state in the keeper's vocabulary for "ended, outcome unknown", so
this reports nothing and the step stays open.

How long that window is decides whether it matters. A scan is handed off
only after the walk's whole bound, hours by default, and a watcher pass
is a minute, so the next scan would have to start within a minute of the
handoff. That is the tail of a tail, and it is the reason this is
tolerable rather than a reason it is right. Closing it means carrying
the file the server said it would write, and asking the filesystem
instead.

## Why it takes a callable

A function from record name to text, rather than a Channel Access
client. The same arrangement the two Globus adapters use: this is
testable against a soft IOC or a dictionary, and a deployment hands over
whatever it already uses to read a record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from reporter.watching import Ending, UnknownWorkError

if TYPE_CHECKING:
    from collections.abc import Callable

REFERENCE_SCHEME: Final = "tomoscan"
REFERENCE_SEPARATOR: Final = "|"
"""How the driving side names a scan it handed over.

Four fields: this word, the server's prefix, and the keeper's execution
and step ids. The separator appears in neither an EPICS record name nor
a UUID, which is why it is that character.
"""

REFERENCE_FIELDS: Final = 4

START_SCAN: Final = "StartScan"
EXECUTION_ID: Final = "KeeperExecutionId"
STEP_ID: Final = "KeeperStepId"
IDLE_VALUE: Final = "Done"
"""The records this reads, and the value that means the scan is over.

The same four names the driving engine uses, and the same idle value it
waits for, so that the two agree about when a scan has finished rather
than each deciding for itself.
"""


@dataclass(frozen=True, slots=True)
class TomoscanScans:
    """How one scan turned out, read from the server that ran it."""

    read: Callable[[str], str]

    def ending(self, reference: str) -> Ending | None:
        prefix, execution_id, step_id = _taken_apart(reference)

        held = (self.read(f"{prefix}{EXECUTION_ID}"), self.read(f"{prefix}{STEP_ID}"))
        if held != (execution_id, step_id):
            return None

        if self.read(f"{prefix}{START_SCAN}") == IDLE_VALUE:
            return Ending("Completed")
        return None


def _taken_apart(reference: str) -> tuple[str, str, str]:
    """The prefix and the two ids, or the news that this is not one of ours.

    A reference belongs to exactly one far side and the others have
    never heard of it, so anything that is not this shape is
    `UnknownWorkError` rather than an error. That is how `across` learns
    it asked the wrong one.
    """
    parts = reference.split(REFERENCE_SEPARATOR)
    if len(parts) != REFERENCE_FIELDS or parts[0] != REFERENCE_SCHEME:
        raise UnknownWorkError(reference)
    _, prefix, execution_id, step_id = parts
    return prefix, execution_id, step_id


CHANNEL_TIMEOUT_SECONDS: Final = 5.0
"""How long one record read is given before it counts as unanswered.

Short, because this is a watcher rather than a driver. A record that
does not answer means this pass cannot say how that scan went, and the
next pass is a minute away.
"""


def over_channel_access(timeout: float = CHANNEL_TIMEOUT_SECONDS) -> Callable[[str], str]:
    """A reader bound to a real control system, for a deployment to hand over.

    Here rather than at the entrypoint because the import is an engine's
    library and only an adapter may name one. `reporter.watcher` calls
    this and stays clean, which is the rule
    `tests/test_the_core_names_no_seam.py` enforces and which caught
    this written the other way round.

    The import is inside the function so that this module stays
    importable without a control system installed. The entrypoint names
    `TomoscanScans` at its top, and a deployment asking only after
    Globus work should not need pyepics to start.

    A fresh channel per read rather than a cached one. This runs once a
    minute over a handful of records, so caching would save nothing and
    would cost a watcher holding channels to every beamline it had ever
    been asked about.
    """
    import epics

    def read(name: str) -> str:
        return str(epics.caget(name, as_string=True, timeout=timeout) or "")

    return read


__all__ = [
    "CHANNEL_TIMEOUT_SECONDS",
    "EXECUTION_ID",
    "IDLE_VALUE",
    "START_SCAN",
    "STEP_ID",
    "TomoscanScans",
    "over_channel_access",
]
