"""An engine seam over a reconstruction run somewhere else, for the one this facility runs.

A file is moved to a computing facility and something there reads it, so
reconstructing it is a step like any other: it is asked for by name, it is
given parameters, and it either finished or it did not. That is what
`Running` is, and a reconstruction needs nothing added to it.

What it needs is the half of that seam `globus_transfer` was the first to
use. A reconstruction runs for hours, far longer than a walk can hold a
claim, so handing the work off is the ordinary outcome here rather than
the exceptional one. The task id the service returns is what makes that a
result instead of a shrug.

## It imports nothing, and that is the pattern rather than an economy

`Computing` is written out here, which is submit and ask, and a deployment
hands over something that satisfies them. So the package gains no
dependency on a compute library, this module is testable without a
network, and a facility that reconstructs its data another way writes
forty lines rather than changing this one.

It also keeps the credential out, and it keeps the allocation out. What
endpoint to submit to, under which project, on how many nodes, in which
container, is a deployment's business and is not reachable from a step.
A procedure that could name its own node count could spend an allocation
while reading like any other step, which is the same reason
`GlobusTransfer` refuses to take its collections from one.

## Why a succeeded task is not a succeeded reconstruction

The two come apart here in a way they do not for a transfer, and this is
the thing this module exists to get right.

What runs on the far side is a command, and the service reports whether
it managed to run it. A reconstruction that started, read its input,
and exited non-zero is a task the service calls successful. Reporting
that as `Done` would file a reconstruction that produced nothing as one
that produced something, and the record would carry an address nobody can
open.

So `Said` has two fields rather than being the one string `Transferring`
returns. A deployment answers with the state it reached and with what the
far side said about it, and a non-zero exit is reported here as a refusal
with that reason attached. The profile is what knows how to read its own
service; this module only insists that it does.

## Why the citation goes in the label and is not read back

`tomoscan_engine` writes its citation into records and reads it back,
because a record holds its last value and a scan run with no citation
after one that had ids would report somebody else's. A submitted task
cannot be stale: what is attached to it is attached when it is created
and belongs to that task forever. So the rule `Running` states applies
instead: given no citation, write nothing at all.

## What a bound running out is not

Not a failure, and not a success either. The reconstruction is still
going, the service still knows about it, and nothing here has any
business cancelling it: a walk that stopped waiting is a fact about this
process rather than about the work. The task id goes out as a handoff and
the step ends there, which for a run measured in hours is what will
usually happen.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Protocol, runtime_checkable

from conductor.seams import Ran, RoutineNotRunHereError, WorkHandedOffError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from conductor.seams import Citation

SOURCE_PATH: Final = "source_path"
"""The one parameter a step must carry: what to reconstruct.

One dataset and not a directory. A step that reconstructed whatever
happened to be in a directory would reconstruct a different set depending
on when it ran, and the record would say it had done the same thing both
times. It is the rule `globus_transfer` states about what it moves, and it
holds for the same reason.
"""

SUCCEEDED: Final = "SUCCEEDED"
FAILED: Final = "FAILED"
"""The two states a reconstruction stops in. Anything else means it is still going.

This module's vocabulary and not any service's. A deployment maps whatever
its own service says onto these, which is the work a profile does and the
reason this module needs no compute library to be read or tested.
"""

LABEL_LIMIT: Final = 128
"""How long a label may be. A deployment attaches it to the work it submits."""


class ComputeError(RuntimeError):
    """A reconstruction that could not be asked for, or that the far side refused."""


class UnknownRoutineError(ComputeError, RoutineNotRunHereError):
    """A routine this engine was not told it runs.

    Both parents, the way `globus_transfer` does it: the walk tells a
    routine nothing runs apart from an engine that broke, and reports the
    first as declined rather than as a fault.
    """

    def __init__(self, routine: str, known: frozenset[str]) -> None:
        RoutineNotRunHereError.__init__(self, routine, f"this compute engine runs {sorted(known)}")


class ComputeRefusedError(ComputeError):
    """The far side took the work and then reported it did not succeed.

    `said` carries whatever the deployment could say about why, which for
    a reconstruction is the part a person needs: a command that exited
    non-zero has a reason, and a task id alone sends somebody to a web
    console to find it.
    """

    def __init__(self, routine: str, reference: str, state: str, said: str) -> None:
        self.routine = routine
        self.reference = reference
        self.state = state
        self.said = said
        because = f": {said}" if said else ""
        super().__init__(
            f"{routine!r} was accepted as {reference} and the far side reported {state!r}{because}"
        )


@dataclass(frozen=True, slots=True)
class Said:
    """What the far side says about work it was given.

    Two fields rather than one, because a compute service answers two
    questions and a transfer service answers one. `state` is whether the
    work has stopped and how, in this module's vocabulary. `detail` is
    why, and is empty when there is nothing to add.
    """

    state: str
    detail: str = ""

    @property
    def is_settled(self) -> bool:
        """Whether the work has stopped, either way."""
        return self.state in (SUCCEEDED, FAILED)


@runtime_checkable
class Computing(Protocol):
    """Submitting a reconstruction and asking how it is going.

    Two methods, written out rather than imported. A deployment satisfies
    them over whatever reconstructs its data, and the names are this
    package's rather than any service's.
    """

    def submit(
        self,
        *,
        source_path: str,
        settings: Mapping[str, object],
        label: str | None,
    ) -> str:
        """Start reconstructing this, and say what the far side calls the work."""
        ...

    def state(self, reference: str) -> Said:
        """What the far side says about work it was given."""
        ...


@dataclass(frozen=True, slots=True)
class GlobusCompute:
    """Reconstructs one dataset per step, and says where the work went.

    Nothing about the allocation is here and nothing about it is reachable
    from a step: which endpoint, which project, how many nodes and which
    container belong to the deployment that holds them, and a step that
    could name them could spend an allocation while reading like any other
    step.

    What a step does carry is what to reconstruct and how. `source_path`
    is required and everything else is handed through as a setting, so the
    record says which rotation axis and which energy a reconstruction was
    asked for rather than leaving them to whatever a file on a host last
    said. That is the arrangement `tomoscan_engine` already has with its
    scan parameters.
    """

    computes: Computing
    routines: frozenset[str]
    settle_timeout: float = 600.0
    poll_interval: float = 15.0
    defaults: Mapping[str, object] = field(default_factory=dict[str, object])
    """What a step leaves unsaid, which a deployment may fill in.

    Empty by default, because a default that this package chose would be
    a reconstruction setting decided by the wrong people. A deployment
    that has house settings puts them here and a step overrides any of
    them by naming it.
    """

    def run(self, routine: str, parameters: Mapping[str, object], cites: Citation | None) -> Ran:
        """Reconstruct what the step names, and wait for it up to the bound."""
        if routine not in self.routines:
            raise UnknownRoutineError(routine, self.routines)

        source_path = str(parameters.get(SOURCE_PATH, "")).strip()
        if not source_path:
            raise ComputeError(
                f"{routine!r} was given no {SOURCE_PATH}, so there is nothing to reconstruct"
            )

        reference = self.computes.submit(
            source_path=source_path,
            settings=self._settings_for(parameters),
            label=_label(cites),
        )

        said = self._await_settled(reference)
        if said is None:
            raise WorkHandedOffError(routine=routine, reference=reference)
        if said.state == FAILED:
            raise ComputeRefusedError(routine, reference, said.state, said.detail)
        return Ran(cites=cites, engine_reference=reference, said=said.state)

    def _settings_for(self, parameters: Mapping[str, object]) -> Mapping[str, object]:
        """The deployment's settings with the step's written over them.

        `source_path` is dropped because it is the subject rather than a
        setting, and passing it through as one would hand the far side a
        reconstruction option nothing answers to.
        """
        settings = dict(self.defaults)
        settings.update({k: v for k, v in parameters.items() if k != SOURCE_PATH})
        return settings

    def _await_settled(self, reference: str) -> Said | None:
        """What the reconstruction stopped in, or nothing if the bound ran out."""
        deadline = time.monotonic() + self.settle_timeout
        while True:
            said = self.computes.state(reference)
            if said.is_settled:
                return said
            if time.monotonic() >= deadline:
                return None
            time.sleep(self.poll_interval)


def _label(cites: Citation | None) -> str | None:
    """The keeper's ids, short enough for a deployment to attach.

    `None` where there is no citation, which is the rule `Running`
    states: an adapter given none writes no keys rather than inventing
    them. A label is built fresh for every submission, so nothing stale
    can be left behind by doing nothing, which is the whole difference
    from an engine that writes into records.
    """
    if cites is None:
        return None
    return f"cora {cites.execution_id} {cites.step_id}"[:LABEL_LIMIT]


__all__ = [
    "FAILED",
    "SOURCE_PATH",
    "SUCCEEDED",
    "ComputeError",
    "ComputeRefusedError",
    "Computing",
    "GlobusCompute",
    "Said",
    "UnknownRoutineError",
]
