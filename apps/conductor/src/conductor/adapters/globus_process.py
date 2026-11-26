"""An engine seam over processing run somewhere else, inside a place a move reached.

A file is moved to a computing facility and something there reads it, so
processing it is a step like any other: it is asked for by name, it is
given parameters, and it either finished or it did not. That is what
`Running` is, and processing needs nothing added to it.

What it needs is the half of that seam `globus_move` was the first to
use. A run can take longer than a walk should hold a claim, so handing
the work off is an ordinary outcome here rather than an exceptional one.
The task id the service returns is what makes that a result instead of a
shrug.

## A place, a path and a configuration

A step names a configuration, a place, an input and an output, and may
override settings the configuration already holds. The place resolves to
a folder on the compute host through the deployment's own settings, so
the input is the same path a move put there and the output has a location
in the same place, which is what lets whatever watches the work record
the result.

A configuration is a name for a set of settings, held by the deployment,
so a hundred runs with one setup repeat nothing. An override can only
change a setting the configuration holds, which catches a misspelt
setting before anything is submitted and keeps every setting documented
in some configuration. Paths are refused rather than normalised when
they start at a root or climb out of the place, the rule the mover keeps.

## Where a run's settings come from

From the keeper. A step's `config` names a setup the keeper holds, the
keeper locks in the revision the run uses when it dispatches the
execution, and the work intake reads that revision back and hands it over
under `seams.APPLIED_SETUP`, with the step's override already written
over it. So the settings an engine applies are the ones the record says
the run was asked for, and no host holds a copy to drift.

A deployment may still hold configurations of its own, and they are what
a step that arrives without a setup is processed by: an execution
dispatched before the keeper locked setups in carries none. An override is
checked against a held configuration exactly as the keeper checks one
against a setup.

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
the step ends there, and whatever watches the far side records how the
run ended.
"""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Protocol, cast, runtime_checkable

from conductor.seams import APPLIED_SETUP, Ran, RoutineNotRunHereError, Said, WorkHandedOffError

if TYPE_CHECKING:
    from conductor.seams import Citation

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
"""The two states a run stops in. Anything else means it is still going.

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
        output_path: str,
    ) -> str:
        """Start processing this into that folder, and say what the far side calls the work.

        Both paths are on the compute host. The output is a folder, because
        a run writes more than one file and a log beside them.
        """
        ...

    def state(self, reference: str) -> Said:
        """What the far side says about work it was given."""
        ...


@dataclass(frozen=True, slots=True)
class GlobusProcess:
    """Processes one input into one output inside a named place, by a named configuration.

    `places` maps each place this engine can read to its folder on the
    compute host. `configs` maps a configuration name to its settings, for
    a step that arrives without a setup from the keeper, and may be empty
    once every step comes with one. Both are the deployment's, and a step
    names neither's contents: a step that could name a folder could write
    anywhere the compute host reaches, and one that could add settings
    freely would be a configuration nobody reviewed.
    """

    computes: Computing
    routines: frozenset[str]
    places: Mapping[str, str]
    configs: Mapping[str, Mapping[str, object]] = field(
        default_factory=dict[str, Mapping[str, object]]
    )
    derived: frozenset[str] = frozenset()
    """The settings the deployment works out for each run, which no setup may hold.

    A configurations file holding one is refused when the engine is built.
    A setup arrives with each step instead, so one holding a derived
    setting is refused before its run is submitted: the run would use the
    worked out value and the record would name the setup's.
    """
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
        """The settings this run applies: its setup's, or a held configuration's.

        A setup handed over with the step wins, because it is what the
        record says the run used and its override is already applied.
        Without one, the named configuration's settings, with the step's
        overrides written over them.
        """
        applied = parameters.get(APPLIED_SETUP)
        if applied is not None:
            settings = _applied_settings(applied)
            clashing = sorted(set(settings) & self.derived)
            if clashing:
                raise ProcessRefusedError(
                    f"the setup handed with this step holds {clashing}, which this engine "
                    "works out for each run from its input and output"
                )
            return settings
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


def _applied_settings(applied: object) -> dict[str, object]:
    """The settings a step's applied setup carries, refused if they cannot be read."""
    if not isinstance(applied, dict):
        raise ProcessRefusedError(f"the setup handed with this step is not a table: {applied!r}")
    settings = cast("dict[str, object]", applied).get("settings")
    if not isinstance(settings, dict):
        raise ProcessRefusedError("the setup handed with this step carries no table of settings")
    return dict(cast("dict[str, object]", settings))


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
    "SUCCEEDED",
    "ComputeError",
    "ComputeRefusedError",
    "Computing",
    "GlobusProcess",
    "ProcessRefusedError",
    "SettingsError",
    "UnknownRoutineError",
    "configurations_from",
    "places_from",
]
