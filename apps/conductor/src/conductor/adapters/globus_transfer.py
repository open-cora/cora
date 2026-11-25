"""An engine seam over a file transfer, shaped for the one this facility runs.

A scan produces a file at a beamline and the work that reads it happens
somewhere else, so moving it is a step like any other: it is asked for by
name, it is given parameters, and it either finished or it did not. That
is what `Running` is, and a transfer needs nothing added to it.

What it does need is the other half of that seam, which existed before
this and had no user. A transfer runs for minutes at best and hours at
worst, far longer than a walk can reasonably hold a claim, so this is the
first adapter that routinely hands work off rather than waiting it out.
The task id the service returns is the reference that makes a handoff an
outcome rather than a shrug: something watching the far side resolves it
later, needing no claim and no walk.

## Two engines: one bound to a pair of collections, one to a set of places

`GlobusTransfer` is built with a source collection and a destination
collection, and a step names only the file. That is what stops a
procedure moving a beamline's data somewhere it was not sent, and its
price is that one engine moves one way: a chain with a trip home needs a
second engine and a second routine, and a chain of four hops would need
four.

`GlobusMove` keeps the rule and drops the price. It is built with places,
each a name the facility gives somewhere data can be, which a deployment
resolves to a collection and a root folder, and with the routes between
them it may move along. A step names a path and two places and never a
collection, so it can choose among routes somebody installed and cannot
invent one. One engine then serves every hop, and what tells two hops
apart is the pair of names each step carries.

The path is relative to the place it leaves and lands at the same
relative path in the place it reaches, so one path names the data at
every stop of a chain. A path ending in a slash is a folder and
everything under it. A path that starts at a collection's root, or has an
empty, "." or ".." segment, is refused rather than normalised, because a
place's root is the bound on what a step can reach.

`GlobusTransfer` stays for deployments whose run tables still name the
two direction-bound profiles, and goes when none does.

## It imports nothing, and that is the pattern rather than an economy

`bluesky_engine` takes a callable and `http_tasking` writes out the shape
of a client. This writes out `Transferring`, which is submit and ask, and
a deployment hands it something that satisfies them. So the package gains
no dependency on a transfer library, this module is testable without a
network, and a facility that moves its data another way writes forty
lines rather than changing this one.

It also keeps the credential out. Whatever authorizes a transfer belongs
to the deployment that has one, and nothing here can be made to hold a
token by configuring it wrongly.

## Why the citation goes in the label and is not read back

`tomoscan_engine` writes its citation into records and reads it back,
because a record holds its last value and a scan run with no citation
after one that had ids would report somebody else's. A task label cannot
be stale: it is set when the task is created and belongs to that task
forever. So the `bluesky_engine` rule applies instead, which is the one
`Running` states: given no citation, write nothing at all.

## What a bound running out is not

Not a failure, and not a success either. The transfer is still going, the
service still knows about it, and nothing here has any business cancelling
it: a walk that stopped waiting is a fact about this process rather than
about the work. So the task id goes out as a handoff and the step ends
there.

A transfer the service reports as failed is different and raises, because
the far side has finished and said no.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from conductor.seams import Ran, RoutineNotRunHereError, Said, WorkHandedOffError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from conductor.seams import Citation

SOURCE_PATH: Final = "source_path"
"""The one parameter a step must carry: what to move.

One file and not a directory listing. A step that moved whatever happened
to be in a directory would move a different set depending on when it ran,
and the record would say it had moved the same thing both times.
"""

PATH: Final = "path"
"""What a move carries: where the data sits inside the place it leaves.

Relative to that place's root, and the same at every place it reaches, so
a chain of moves names one dataset by one path however many hops it
takes. Ending in a slash means a folder and everything under it, and what
the folder held when it moved is the transfer task's own record of it.
"""

FROM: Final = "from"
TO: Final = "to"
"""The two places a move names: names, never addresses.

Each resolves through the places the engine was built with, so a step
chooses among routes a deployment installed and cannot add one.
"""

_PLACE_NAME: Final = re.compile(r"[a-z0-9][a-z0-9-]*")
"""How a place may be spelled: lowercase letters, digits and hyphens.

The alphabet a beamline slug uses and the one the move operation's schema
enumerates, so a name in a procedure and a name in a deployment either
match character for character or fail to.
"""

SUCCEEDED: Final = "SUCCEEDED"
FAILED: Final = "FAILED"
"""The two states a transfer stops in. Anything else means it is still going.

This package's words, which a deployment maps its service's onto. They
are re-exported from `conductor.seams` so both engine seams answer in
one vocabulary.
"""

LABEL_LIMIT: Final = 128
"""How long a label may be. Longer ones are refused by the service."""


class TransferError(RuntimeError):
    """A transfer that could not be asked for, or that the service refused."""


class UnknownRoutineError(TransferError, RoutineNotRunHereError):
    """A routine this engine was not told it runs.

    Both parents, the way `tomoscan_engine` does it: the walk tells a
    routine nothing runs apart from an engine that broke, and reports the
    first as declined rather than as a fault.
    """

    def __init__(self, routine: str, known: frozenset[str]) -> None:
        RoutineNotRunHereError.__init__(self, routine, f"this transfer engine runs {sorted(known)}")


class NoRouteError(TransferError):
    """A move naming a place this engine does not know, or a pair it may not move between.

    The route list is the gate a step cannot widen. A procedure may name
    any place the facility knows, and only the pairs a deployment
    installed will move.
    """


class PathRefusedError(TransferError):
    """A path that names nothing, or that could reach outside its place."""


class PlacesError(ValueError):
    """A deployment's places or routes that cannot be read.

    Raised while the engine is built, which happens at startup, so a
    deployment that wrote one wrong finds out before a procedure reaches a
    move rather than during one.
    """


class TransferRefusedError(TransferError):
    """The service took the transfer and then reported it failed.

    `said` carries whatever the deployment could say about why. A
    transfer fails for reasons a person can act on, a missing source or
    a permission, and a task id alone sends them to a web console to
    find out which.
    """

    def __init__(self, routine: str, reference: str, state: str, said: str = "") -> None:
        self.routine = routine
        self.reference = reference
        self.state = state
        self.said = said
        because = f": {said}" if said else ""
        super().__init__(
            f"{routine!r} was accepted as {reference} and the service said {state!r}{because}"
        )


@dataclass(frozen=True, slots=True)
class Item:
    """One file or one folder, where it is and where it should end up.

    `recursive` says the source is a folder and everything under it moves.
    It is false for a file, which is every item `GlobusTransfer` sends.
    """

    source_path: str
    destination_path: str
    recursive: bool = False


@dataclass(frozen=True, slots=True)
class Place:
    """Somewhere data can be, named by the facility and addressed by a deployment.

    The name is what a procedure writes. The collection and the root are
    where that name leads at this deployment, and a step can name neither.
    """

    name: str
    collection: str
    root: str

    def at(self, path: str) -> str:
        """Where a path inside this place sits on its collection."""
        return f"{self.root.rstrip('/')}/{path}"


@dataclass(frozen=True, slots=True)
class Places:
    """The places one engine knows, and which moves between them it may make."""

    known: Mapping[str, Place]
    routes: frozenset[tuple[str, str]]

    @classmethod
    def parse(cls, places: str, routes: str) -> Places:
        """Read the two settings a deployment writes, refusing anything ambiguous.

        Each place is name=collection:root and each route is from>to, both
        separated by whitespace. A collection's id holds no colon, so the
        first one ends it; a root is an absolute path on that collection.
        """
        known: dict[str, Place] = {}
        for entry in places.split():
            name, equals, location = entry.partition("=")
            collection, colon, root = location.partition(":")
            if not (equals and colon and collection):
                raise PlacesError(f"{entry!r} is not a place written as name=collection:root")
            if not _PLACE_NAME.fullmatch(name):
                raise PlacesError(
                    f"{name!r} is not a place name: lowercase letters, digits and hyphens only"
                )
            if not root.startswith("/"):
                raise PlacesError(
                    f"{name!r} is rooted at {root!r}, which is not an absolute path on its "
                    "collection"
                )
            if name in known:
                raise PlacesError(f"{name!r} is listed twice, so a move to it is ambiguous")
            known[name] = Place(name=name, collection=collection, root=root)
        if not known:
            raise PlacesError("no places are listed, so this engine has nowhere to move anything")

        pairs: set[tuple[str, str]] = set()
        for entry in routes.split():
            origin, arrow, destination = entry.partition(">")
            if not (arrow and origin and destination):
                raise PlacesError(f"{entry!r} is not a route written as from>to")
            for name in (origin, destination):
                if name not in known:
                    raise PlacesError(
                        f"the route {entry!r} names {name!r}, which is not among the places "
                        f"{sorted(known)}"
                    )
            if origin == destination:
                raise PlacesError(f"the route {entry!r} leaves and arrives at one place")
            pairs.add((origin, destination))
        if not pairs:
            raise PlacesError("no routes are listed, so this engine may make no move at all")
        return cls(known=MappingProxyType(known), routes=frozenset(pairs))

    def between(self, origin: object, destination: object) -> tuple[Place, Place]:
        """The two places a step names, if this engine may move from the first to the second."""
        names = (str(origin or "").strip(), str(destination or "").strip())
        if not all(names):
            raise NoRouteError(f"a move names both {FROM!r} and {TO!r}, and this one did not")
        for name in names:
            if name not in self.known:
                raise NoRouteError(
                    f"{name!r} is not a place this engine knows; it knows {sorted(self.known)}"
                )
        if names not in self.routes:
            installed = sorted(f"{a}>{b}" for a, b in self.routes)
            raise NoRouteError(
                f"there is no route from {names[0]!r} to {names[1]!r}; this engine moves "
                f"{installed}"
            )
        return self.known[names[0]], self.known[names[1]]


@runtime_checkable
class Transferring(Protocol):
    """Submitting a move and asking how it is going.

    Two methods, written out rather than imported. A deployment satisfies
    them over whatever moves its data, and the names are this package's
    rather than any service's.
    """

    def submit(
        self,
        *,
        source: str,
        destination: str,
        items: Sequence[Item],
        label: str | None,
    ) -> str:
        """Start moving these, and say what the far side calls the work."""
        ...

    def state(self, reference: str) -> Said:
        """What the far side says about work it was given, and why.

        A `Said` and not a bare state, which a measurement forced. A
        transfer whose source does not exist stays active for a day,
        retrying, with the reason in a field beside the status. An
        adapter told only the status cannot tell that from a large file
        still moving, so a deployment answers with both.
        """
        ...


@dataclass(frozen=True, slots=True)
class GlobusTransfer:
    """Moves one file per step, and says where the work went.

    `source` and `destination` name collections and are a deployment's
    fact, not a step's. A step that named its own endpoints could move a
    beamline's data anywhere, and the procedure that did it would read
    like any other.

    `destination_prefix` is joined to the file's own name. Nothing takes
    a destination path from a step for the same reason.
    """

    transfers: Transferring
    routines: frozenset[str]
    source: str
    destination: str
    destination_prefix: str
    settle_timeout: float = 600.0
    poll_interval: float = 5.0

    def run(self, routine: str, parameters: Mapping[str, object], cites: Citation | None) -> Ran:
        """Move what the step names, and wait for it up to the bound."""
        if routine not in self.routines:
            raise UnknownRoutineError(routine, self.routines)

        source_path = str(parameters.get(SOURCE_PATH, "")).strip()
        if not source_path:
            raise TransferError(
                f"{routine!r} was given no {SOURCE_PATH}, so there is nothing to move"
            )

        item = Item(
            source_path=source_path,
            destination_path=self._destination_for(source_path),
        )
        reference = self.transfers.submit(
            source=self.source,
            destination=self.destination,
            items=(item,),
            label=_label(cites),
        )

        said = _settled(self.transfers, reference, self.settle_timeout, self.poll_interval)
        if said is None:
            raise WorkHandedOffError(routine=routine, reference=reference)
        if said.state == FAILED:
            raise TransferRefusedError(routine, reference, said.state, said.detail)
        return Ran(cites=cites, engine_reference=reference, said=said.state)

    def _destination_for(self, source_path: str) -> str:
        """Where one file lands, which is the prefix and its own name."""
        name = source_path.rstrip("/").rsplit("/", 1)[-1]
        return f"{self.destination_prefix.rstrip('/')}/{name}"


@dataclass(frozen=True, slots=True)
class GlobusMove:
    """Moves one file or folder between two named places, and says where the work went.

    Where `GlobusTransfer` is bound to one pair of collections, this is
    bound to `Places`: every place a deployment named and the routes
    between them. So one engine serves every hop it was given, and a chain
    of any length is the same operation at each step.
    """

    transfers: Transferring
    routines: frozenset[str]
    places: Places
    settle_timeout: float = 600.0
    poll_interval: float = 5.0

    def run(self, routine: str, parameters: Mapping[str, object], cites: Citation | None) -> Ran:
        """Move what the step names between the places it names, and wait up to the bound."""
        if routine not in self.routines:
            raise UnknownRoutineError(routine, self.routines)

        path, folder = _within(parameters.get(PATH))
        origin, destination = self.places.between(parameters.get(FROM), parameters.get(TO))
        reference = self.transfers.submit(
            source=origin.collection,
            destination=destination.collection,
            items=(Item(origin.at(path), destination.at(path), recursive=folder),),
            label=_label(cites),
        )

        said = _settled(self.transfers, reference, self.settle_timeout, self.poll_interval)
        if said is None:
            raise WorkHandedOffError(routine=routine, reference=reference)
        if said.state == FAILED:
            raise TransferRefusedError(routine, reference, said.state, said.detail)
        return Ran(cites=cites, engine_reference=reference, said=said.state)


def _within(path: object) -> tuple[str, bool]:
    """A path inside a place and whether it is a folder, refused if it could leave the place.

    Refused rather than normalised. A place's root bounds what a step can
    read or write, and quietly resolving a climb out of it would make that
    bound a suggestion.
    """
    text = str(path or "").strip()
    if not text:
        raise PathRefusedError(f"a move was given no {PATH!r}, so there is nothing to move")
    if text.startswith("/"):
        raise PathRefusedError(
            f"{text!r} starts at a collection's root; a move's {PATH!r} is relative to the "
            "place it leaves"
        )
    if any(ord(character) < 32 for character in text):
        raise PathRefusedError(f"{text!r} holds a control character")
    folder = text.endswith("/")
    segments = (text[:-1] if folder else text).split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise PathRefusedError(
            f"{text!r} has an empty, '.' or '..' segment, so it could name somewhere outside "
            "its place"
        )
    return text, folder


def _settled(transfers: Transferring, reference: str, timeout: float, poll: float) -> Said | None:
    """What a transfer stopped in, or nothing if the bound ran out."""
    deadline = time.monotonic() + timeout
    while True:
        said = transfers.state(reference)
        if said.is_settled:
            return said
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll)


def _label(cites: Citation | None) -> str | None:
    """The keeper's ids, short enough for the service to accept.

    `None` where there is no citation, which is the rule `Running`
    states: an adapter given none writes no keys rather than inventing
    them. A label is built fresh for every task, so nothing stale can be
    left behind by doing nothing, which is the whole difference from an
    engine that writes into records.
    """
    if cites is None:
        return None
    return f"cora {cites.execution_id} {cites.step_id}"[:LABEL_LIMIT]


__all__ = [
    "FAILED",
    "FROM",
    "PATH",
    "SOURCE_PATH",
    "SUCCEEDED",
    "TO",
    "GlobusMove",
    "GlobusTransfer",
    "Item",
    "NoRouteError",
    "PathRefusedError",
    "Place",
    "Places",
    "PlacesError",
    "TransferError",
    "TransferRefusedError",
    "Transferring",
    "UnknownRoutineError",
]
