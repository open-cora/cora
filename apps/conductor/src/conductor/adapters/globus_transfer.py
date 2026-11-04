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

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from conductor.seams import Ran, RoutineNotRunHereError, WorkHandedOffError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from conductor.seams import Citation

SOURCE_PATH: Final = "source_path"
"""The one parameter a step must carry: what to move.

One file and not a directory listing. A step that moved whatever happened
to be in a directory would move a different set depending on when it ran,
and the record would say it had moved the same thing both times.
"""

SUCCEEDED: Final = "SUCCEEDED"
FAILED: Final = "FAILED"
"""The two states a transfer stops in. Anything else means it is still going."""

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


class TransferRefusedError(TransferError):
    """The service took the transfer and then reported it failed."""

    def __init__(self, routine: str, reference: str, said: str) -> None:
        self.routine = routine
        self.reference = reference
        self.said = said
        super().__init__(f"{routine!r} was accepted as {reference} and the service said {said!r}")


@dataclass(frozen=True, slots=True)
class Item:
    """One file, where it is and where it should end up."""

    source_path: str
    destination_path: str


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

    def state(self, reference: str) -> str:
        """What the far side says about work it was given."""
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

        said = self._await_settled(reference)
        if said is None:
            raise WorkHandedOffError(routine=routine, reference=reference)
        if said == FAILED:
            raise TransferRefusedError(routine, reference, said)
        return Ran(cites=cites, engine_reference=reference, said=said)

    def _destination_for(self, source_path: str) -> str:
        """Where one file lands, which is the prefix and its own name."""
        name = source_path.rstrip("/").rsplit("/", 1)[-1]
        return f"{self.destination_prefix.rstrip('/')}/{name}"

    def _await_settled(self, reference: str) -> str | None:
        """What the transfer stopped in, or nothing if the bound ran out."""
        deadline = time.monotonic() + self.settle_timeout
        while True:
            said = self.transfers.state(reference)
            if said in (SUCCEEDED, FAILED):
                return said
            if time.monotonic() >= deadline:
                return None
            time.sleep(self.poll_interval)


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
    "SOURCE_PATH",
    "SUCCEEDED",
    "GlobusTransfer",
    "Item",
    "TransferError",
    "TransferRefusedError",
    "Transferring",
    "UnknownRoutineError",
]
