"""Where a move's data arrived, and where a process wrote, recorded in custody.

A move takes whatever sits at one location, a place and a path inside it,
and makes it exist at the same path in another place. The record holds
the step that asked for it and whether it finished, and custody holds
every address each dataset answers to. Neither says, until something
writes it, that the datasets under the moved path now answer to a second
address. This is the part that writes it.

## Why it lives beside the watcher and not in the driver

The driver that ran the move had the answer in hand when the step
returned, and is deliberately not the one to write it: its seams say
why, after a beamline running both recorded one address twice against
one step. Where data went can be read by anything watching the work,
and the record already says it in place names: a finished move put its
path under the place it names as its destination. So this reads the
record, the way the watcher does for handovers, and needs no map from a
transfer service's own addresses back to places.

## What counts as having arrived

A dataset arrives when one of its addresses in the place scheme lay
inside what moved: the moved path itself, or anything under it when the
path names a folder by ending in a slash. A dataset whose address is a
folder does not arrive when only a file inside that folder moved,
because only part of it did.

## Where a process wrote

A process reads an input inside a place and writes into an output folder
in the same place, and the step names both. So a finished process left a
dataset at that folder's place address, which nothing has recorded until
this does: one registration per process, against the step that ran it.
Once recorded, a move of that folder is an ordinary move of a dataset,
so the trip home is recorded as an arrival like any other.

A process is checked against custody before it is recorded, because
registering a dataset is not refused the way recording a second address
is, and every pass meets the same finished processes again. An output
whose address custody already holds is counted as already recorded.

## Why recording twice is safe

Every pass reads the same recent executions, so it meets the same
finished moves again. Recording an address a dataset already holds is
refused by the keeper as a conflict, and that refusal is read here as
already recorded, the way `resolve` reads a start the record already
holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from uuid import UUID

PLACE_SCHEME: Final = "place"
"""The custody scheme for an address inside a named place, written place:path.

One scheme for every place rather than a scheme per place, so the
keeper's open vocabulary gains one word and the place travels in the
value, where a prefix lookup can find everything under a path.
"""

MOVE: Final = "move"
PATH: Final = "path"
FROM: Final = "from"
TO: Final = "to"
"""The operation a move step names, and the three parameters it carries.

Read off the step's procedure, so they have to match the facility
register's spelling, which a check in the tree's own tier compares.
"""

PROCESS: Final = "process"
AT: Final = "at"
OUTPUT: Final = "output"
"""The operation a process step names, and the two parameters saying where it wrote.

A process step carries more than these, and the rest is what it was
asked to do rather than where its result is.
"""


@dataclass(frozen=True, slots=True)
class Move:
    """A move the record says finished: which step, what path, from where to where."""

    execution_id: UUID
    step_id: UUID
    path: str
    origin: str
    destination: str


@dataclass(frozen=True, slots=True)
class Output:
    """A process the record says finished: which step, and the place and folder it wrote."""

    execution_id: UUID
    step_id: UUID
    place: str
    path: str


@dataclass(frozen=True, slots=True)
class Finished:
    """What the record says finished and left data somewhere, read in one pass."""

    moves: tuple[Move, ...]
    outputs: tuple[Output, ...]


@dataclass(frozen=True, slots=True)
class Outputs:
    """What one pass over finished processes did.

    `failed` carries the process and what refused it, so one refusal does
    not hide the rest of the pass.
    """

    processes: int
    recorded: int
    already: int
    failed: tuple[tuple[Output, str], ...]


@dataclass(frozen=True, slots=True)
class Arrivals:
    """What one pass over finished moves did.

    `unmatched` are moves custody held nothing under, which is what a
    first hop looks like when nobody registered where the data started.
    `failed` carries the move and what refused it, so one refusal does
    not hide the rest of the pass.
    """

    moves: int
    recorded: int
    already: int
    unmatched: tuple[Move, ...]
    failed: tuple[tuple[Move, str], ...]


@runtime_checkable
class Placing(Protocol):
    """Asking custody which datasets sit under a path, and recording where data now is."""

    def under(self, prefix: str) -> Sequence[tuple[UUID, str]]:
        """Every dataset holding a place address that starts with the prefix, with that address."""
        ...

    def arrived(self, dataset_id: UUID, held_at: str, move: Move) -> bool:
        """Record one dataset at a new place address, and say whether that was news.

        False when the dataset was already recorded there, which a pass
        meeting the same move twice does by design.
        """
        ...

    def produced(self, output: Output, held_at: str) -> UUID:
        """Record the dataset a process wrote at a place address, and return its id."""
        ...


def address(place: str, path: str) -> str:
    """A place address as custody holds it."""
    return f"{place}:{path}"


def inside(held: str, move: Move) -> str | None:
    """The path of a held address within its place, if it lay inside what moved."""
    origin = address(move.origin, "")
    if not held.startswith(origin):
        return None
    path = held[len(origin) :]
    if move.path.endswith("/"):
        return path if path.startswith(move.path) else None
    return path if path == move.path else None


def record_arrivals(moves: Iterable[Move], placing: Placing) -> Arrivals:
    """Record every dataset each finished move carried at the place it reached.

    Each move is handled on its own. One that raises is reported and the
    pass goes on, because a refusal for one dataset says nothing about
    the next move's.
    """
    counted = recorded = already = 0
    unmatched: list[Move] = []
    failed: list[tuple[Move, str]] = []
    for move in moves:
        counted += 1
        try:
            carried = [
                (dataset_id, path)
                for dataset_id, held in placing.under(address(move.origin, move.path))
                if (path := inside(held, move)) is not None
            ]
            if not carried:
                unmatched.append(move)
                continue
            for dataset_id, path in carried:
                if placing.arrived(dataset_id, address(move.destination, path), move):
                    recorded += 1
                else:
                    already += 1
        except Exception as refused:
            failed.append((move, f"{type(refused).__name__}: {refused}"))
    return Arrivals(
        moves=counted,
        recorded=recorded,
        already=already,
        unmatched=tuple(unmatched),
        failed=tuple(failed),
    )


def record_outputs(outputs: Iterable[Output], placing: Placing) -> Outputs:
    """Record the dataset each finished process wrote, unless custody already holds it there.

    Each process is handled on its own, for the reason `record_arrivals`
    gives. Run before arrivals in a pass, so a move finishing in the same
    pass as the process before it finds what that process wrote.
    """
    counted = recorded = already = 0
    failed: list[tuple[Output, str]] = []
    for output in outputs:
        counted += 1
        held_at = address(output.place, output.path)
        try:
            if any(held == held_at for _, held in placing.under(held_at)):
                already += 1
                continue
            placing.produced(output, held_at)
            recorded += 1
        except Exception as refused:
            failed.append((output, f"{type(refused).__name__}: {refused}"))
    return Outputs(processes=counted, recorded=recorded, already=already, failed=tuple(failed))


__all__ = [
    "AT",
    "FROM",
    "MOVE",
    "OUTPUT",
    "PATH",
    "PLACE_SCHEME",
    "PROCESS",
    "TO",
    "Arrivals",
    "Finished",
    "Move",
    "Output",
    "Outputs",
    "Placing",
    "address",
    "inside",
    "record_arrivals",
    "record_outputs",
]
