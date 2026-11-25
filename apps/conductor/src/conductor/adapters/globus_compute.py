"""An engine seam over a reconstruction run somewhere else, for the one this facility runs.

A file is moved to a computing facility and something there reads it, so
reconstructing it is a step like any other: it is asked for by name, it is
given parameters, and it either finished or it did not. That is what
`Running` is, and a reconstruction needs nothing added to it.

What it needs is the half of that seam `globus_move` was the first to
use. A reconstruction runs for hours, far longer than a walk can hold a
claim, so handing the work off is the ordinary outcome here rather than
the exceptional one. The task id the service returns is what makes that a
result instead of a shrug.

## Two engines: one handed a filesystem path, one a place, a path and a configuration

`GlobusCompute` reconstructs what a step names by its full path on the
compute host, with every setting carried by the step or by one file of
house defaults. `GlobusProcess` is the general form. A step names a
configuration, a place, an input and an output, and may override settings
the configuration already holds. The place resolves to a folder on the
compute host through the deployment's own settings, so the input is the
same path a move put there and the output has a location in the same
place, which is what lets whatever watches the work record the result.

A configuration is a name for a set of settings, held by the deployment,
so a hundred runs with one setup repeat nothing. An override can only
change a setting the configuration holds, which catches a misspelt
setting before anything is submitted and keeps every setting documented
in some configuration. Paths are refused rather than normalised when
they start at a root or climb out of the place, the rule the mover keeps.

`GlobusCompute` stays while recorded procedures still name the older
operation, and goes when none can run.

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
`GlobusMove` takes places from a step and never the collections they
resolve to.

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

import re
import time
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Protocol, cast, runtime_checkable

from conductor.seams import Ran, RoutineNotRunHereError, Said, WorkHandedOffError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from conductor.seams import Citation

SOURCE_PATH: Final = "source_path"
"""The one parameter a step must carry: what to reconstruct.

One dataset and not a directory. A step that reconstructed whatever
happened to be in a directory would reconstruct a different set depending
on when it ran, and the record would say it had done the same thing both
times.
"""

CONFIG: Final = "config"
AT: Final = "at"
INPUT: Final = "input"
OUTPUT: Final = "output"
OVERRIDE: Final = "override"
"""What a process step carries: which configuration, where, what in and what out.

`override` is optional and is a table of settings, so the operation's own
contract stays these five however many settings a configuration holds.
The output names a folder and ends in a slash, because a run writes more
than one file and a log beside them.
"""

_NAME: Final = re.compile(r"[a-z0-9][a-z0-9-]*")
"""How a place or a configuration may be spelled: lowercase letters, digits, hyphens."""

SUCCEEDED: Final = "SUCCEEDED"
FAILED: Final = "FAILED"
"""The two states a reconstruction stops in. Anything else means it is still going.

Re-exported from `conductor.seams`, whose `Said` both engine seams now
answer in. A deployment maps whatever its own service says onto these,
which is the work a profile does and the reason this module needs no
compute library to be read or tested.
"""

LABEL_LIMIT: Final = 128
"""How long a label may be. A deployment attaches it to the work it submits."""


class ComputeError(RuntimeError):
    """A reconstruction that could not be asked for, or that the far side refused."""


class UnknownRoutineError(ComputeError, RoutineNotRunHereError):
    """A routine this engine was not told it runs.

    Both parents, the way `globus_move` does it: the walk tells a
    routine nothing runs apart from an engine that broke, and reports the
    first as declined rather than as a fault.
    """

    def __init__(self, routine: str, known: frozenset[str]) -> None:
        RoutineNotRunHereError.__init__(self, routine, f"this compute engine runs {sorted(known)}")


class ProcessRefusedError(ComputeError):
    """A process step this engine will not submit: an unknown configuration or
    place, a path that could leave its place, or an override of a setting the
    configuration does not hold. Refused before anything reaches the far side.
    """


class SettingsError(ValueError):
    """A deployment's places or configurations that cannot be read.

    Raised while the engine is built, which happens at startup, so a
    deployment that wrote one wrong finds out before a procedure reaches a
    process step rather than during one.
    """


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
        output_path: str | None = None,
    ) -> str:
        """Start reconstructing this, and say what the far side calls the work.

        `output_path` is the folder the result is written into, on the
        compute host. Absent, a deployment derives one from its own results
        setting, which is what the older engine relies on.
        """
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

        said = _settled(self.computes, reference, self.settle_timeout, self.poll_interval)
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


@dataclass(frozen=True, slots=True)
class GlobusProcess:
    """Processes one input into one output inside a named place, by a named configuration.

    `places` maps each place this engine can read to its folder on the
    compute host, and `configs` maps each configuration name to its
    settings. Both are the deployment's, and a step names neither's
    contents: a step that could name a folder could write anywhere the
    compute host reaches, and one that could add settings freely would be
    a configuration nobody reviewed.
    """

    computes: Computing
    routines: frozenset[str]
    places: Mapping[str, str]
    configs: Mapping[str, Mapping[str, object]]
    settle_timeout: float = 600.0
    poll_interval: float = 15.0

    def run(self, routine: str, parameters: Mapping[str, object], cites: Citation | None) -> Ran:
        """Process what the step names where it names, and wait for it up to the bound."""
        if routine not in self.routines:
            raise UnknownRoutineError(routine, self.routines)

        settings = self._settings_for(parameters)
        root = self._root_of(parameters.get(AT))
        source, _ = _within(parameters.get(INPUT), INPUT)
        output, folder = _within(parameters.get(OUTPUT), OUTPUT)
        if not folder:
            raise ProcessRefusedError(
                f"{output!r} is not a folder; a process {OUTPUT!r} ends in a slash"
            )
        reference = self.computes.submit(
            source_path=f"{root}/{source}",
            settings=settings,
            label=_label(cites),
            output_path=f"{root}/{output}",
        )

        said = _settled(self.computes, reference, self.settle_timeout, self.poll_interval)
        if said is None:
            raise WorkHandedOffError(routine=routine, reference=reference)
        if said.state == FAILED:
            raise ComputeRefusedError(routine, reference, said.state, said.detail)
        return Ran(cites=cites, engine_reference=reference, said=said.state)

    def _settings_for(self, parameters: Mapping[str, object]) -> dict[str, object]:
        """The named configuration's settings, with the step's overrides written over them."""
        name = str(parameters.get(CONFIG) or "").strip()
        held = self.configs.get(name)
        if held is None:
            raise ProcessRefusedError(
                f"{name!r} is not a configuration this engine holds; it holds "
                f"{sorted(self.configs)}"
            )
        given: object = parameters.get(OVERRIDE) or {}
        if not isinstance(given, dict):
            raise ProcessRefusedError(f"{OVERRIDE!r} is a table of settings, not {given!r}")
        override = cast("Mapping[str, object]", given)
        settings = dict(held)
        for key, value in override.items():
            if key not in held:
                raise ProcessRefusedError(
                    f"{key!r} is not a setting the configuration {name!r} holds, so it cannot "
                    "be overridden; a setting a run needs belongs in its configuration first"
                )
            settings[key] = value
        return settings

    def _root_of(self, place: object) -> str:
        """The folder a place resolves to on the compute host."""
        name = str(place or "").strip()
        root = self.places.get(name)
        if root is None:
            raise ProcessRefusedError(
                f"{name!r} is not a place this engine can read; it reads {sorted(self.places)}"
            )
        return root.rstrip("/")


def places_from(text: str) -> Mapping[str, str]:
    """Read a deployment's places, each written name=folder and separated by whitespace.

    The folder is where the place's data sits on the compute host, so it is
    an absolute path there.
    """
    places: dict[str, str] = {}
    for entry in text.split():
        name, equals, root = entry.partition("=")
        if not (equals and root):
            raise SettingsError(f"{entry!r} is not a place written as name=folder")
        if not _NAME.fullmatch(name):
            raise SettingsError(f"{name!r} is not a place name: lowercase letters, digits, hyphens")
        if not root.startswith("/"):
            raise SettingsError(f"{name!r} is at {root!r}, which is not an absolute folder")
        if name in places:
            raise SettingsError(f"{name!r} is listed twice")
        places[name] = root
    if not places:
        raise SettingsError("no places are listed, so this engine can read nothing")
    return MappingProxyType(places)


def configurations_from(
    document: Mapping[str, object], derived: frozenset[str]
) -> Mapping[str, Mapping[str, object]]:
    """Read a deployment's named configurations out of its parsed configurations file.

    Each is a table under `config`, named in the alphabet a place uses. A
    configuration may not hold a setting in `derived`, because those are
    worked out from a step's input and output and a configuration naming
    one would point every run at one file.
    """
    given = document.get(CONFIG)
    if not isinstance(given, dict) or not given:
        raise SettingsError(f"the configurations file has no [{CONFIG}.<name>] tables")
    tables = cast("Mapping[str, Any]", given)
    configs: dict[str, Mapping[str, object]] = {}
    for name, table in tables.items():
        if not _NAME.fullmatch(name):
            raise SettingsError(
                f"{name!r} is not a configuration name: lowercase letters, digits, hyphens"
            )
        if not isinstance(table, dict) or not table:
            raise SettingsError(f"the configuration {name!r} is not a table of settings")
        settings = cast("Mapping[str, object]", table)
        clashing = sorted(set(settings) & derived)
        if clashing:
            raise SettingsError(
                f"the configuration {name!r} sets {clashing}, which a run works out from its "
                "input and output"
            )
        configs[name] = MappingProxyType(dict(settings))
    return MappingProxyType(configs)


def _within(path: object, parameter: str) -> tuple[str, bool]:
    """A path inside a place and whether it is a folder, refused if it could leave the place.

    The same rule the mover keeps, written out here because adapters do
    not import each other; a test feeds both the same paths so the two
    copies cannot drift apart unnoticed.
    """
    text = str(path or "").strip()
    if not text:
        raise ProcessRefusedError(f"a process step was given no {parameter!r}")
    if text.startswith("/"):
        raise ProcessRefusedError(
            f"{text!r} starts at a root; a process {parameter!r} is relative to its place"
        )
    if any(ord(character) < 32 for character in text):
        raise ProcessRefusedError(f"{text!r} holds a control character")
    folder = text.endswith("/")
    segments = (text[:-1] if folder else text).split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise ProcessRefusedError(
            f"{text!r} has an empty, '.' or '..' segment, so it could name somewhere outside "
            "its place"
        )
    return text, folder


def _settled(computes: Computing, reference: str, timeout: float, poll: float) -> Said | None:
    """What the work stopped in, or nothing if the bound ran out."""
    deadline = time.monotonic() + timeout
    while True:
        said = computes.state(reference)
        if said.is_settled:
            return said
        if time.monotonic() >= deadline:
            return None
        time.sleep(poll)


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
    "AT",
    "CONFIG",
    "FAILED",
    "INPUT",
    "OUTPUT",
    "OVERRIDE",
    "SOURCE_PATH",
    "SUCCEEDED",
    "ComputeError",
    "ComputeRefusedError",
    "Computing",
    "GlobusCompute",
    "GlobusProcess",
    "ProcessRefusedError",
    "SettingsError",
    "UnknownRoutineError",
    "configurations_from",
    "places_from",
]
