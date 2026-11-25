"""Processing an input into an output inside a named place, against a service that is a double.

`GlobusProcess` is what lets one operation cover any processing a
deployment configures: a step names a configuration, a place, an input
and an output, and the engine resolves the place and the configuration
through what the deployment installed. The cases below are the ways that
could go wrong without anything noticing.

A path that climbs out of its place would make the place no bound at all,
so the mover's rule is checked against this engine's with the same paths.
An override of a setting no configuration holds would be a misspelling
submitted as a setting. And an override that leaked into the configuration
would change every later run that named it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest

from conductor.adapters.globus_move import GlobusMove, Item, PathRefusedError, Places
from conductor.adapters.globus_process import (
    FAILED,
    SUCCEEDED,
    ComputeRefusedError,
    GlobusProcess,
    ProcessRefusedError,
    SettingsError,
    UnknownRoutineError,
    configurations_from,
    places_from,
)
from conductor.seams import Citation, RoutineNotRunHereError, Said, WorkHandedOffError

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

PROCESS = "process"
PLACES = "alcf=/srv/alcf/cora nersc=/srv/nersc/"
DERIVED = frozenset({"file-name", "out-path-name", "logs-home"})


def _configs() -> dict[str, Mapping[str, object]]:
    return {
        "tomocupy-19bm": {"rotation-axis": 1628.5, "energy": 92.0, "binning": 0},
        "tomocupy-try": {"rotation-axis": 1500.0, "reconstruction-type": "try"},
    }


@dataclass(frozen=True)
class _Submitted:
    source_path: str
    settings: dict[str, object]
    label: str | None
    output_path: str


@dataclass
class _Service:
    """A compute service that records what it was asked and reports what it was handed."""

    says: list[Said] = field(default_factory=lambda: [Said(SUCCEEDED)])
    submitted: list[_Submitted] = field(default_factory=list[_Submitted])

    def submit(
        self,
        *,
        source_path: str,
        settings: Mapping[str, object],
        label: str | None,
        output_path: str,
    ) -> str:
        self.submitted.append(_Submitted(source_path, dict(settings), label, output_path))
        return "task-1"

    def state(self, reference: str) -> Said:
        return self.says.pop(0) if len(self.says) > 1 else self.says[0]


def _processor(
    service: _Service, configs: Mapping[str, Mapping[str, object]] | None = None
) -> GlobusProcess:
    return GlobusProcess(
        computes=service,
        routines=frozenset({PROCESS}),
        places=places_from(PLACES),
        configs=_configs() if configs is None else configs,
        settle_timeout=0.05,
        poll_interval=0.0,
    )


def _step(**changes: object) -> dict[str, object]:
    step: dict[str, object] = {
        "config": "tomocupy-19bm",
        "at": "alcf",
        "input": "Monet/2026-2/scan_0006.h5",
        "output": "analysis/scan_0006/",
    }
    step.update(changes)
    return step


def test_a_process_reads_its_input_and_writes_its_output_inside_the_place_it_names() -> None:
    service = _Service()

    ran = _processor(service).run(PROCESS, _step(), None)

    submitted = service.submitted[0]
    assert submitted.source_path == "/srv/alcf/cora/Monet/2026-2/scan_0006.h5"
    assert submitted.output_path == "/srv/alcf/cora/analysis/scan_0006/"
    assert ran.engine_reference == "task-1"
    assert ran.said == SUCCEEDED


def test_a_place_written_with_a_trailing_slash_resolves_without_doubling_it() -> None:
    service = _Service()

    _processor(service).run(PROCESS, _step(at="nersc"), None)

    assert service.submitted[0].source_path == "/srv/nersc/Monet/2026-2/scan_0006.h5"
    assert service.submitted[0].output_path == "/srv/nersc/analysis/scan_0006/"


def test_a_process_is_handed_every_setting_the_configuration_it_names_holds() -> None:
    service = _Service()

    _processor(service).run(PROCESS, _step(config="tomocupy-try"), None)

    assert service.submitted[0].settings == {
        "rotation-axis": 1500.0,
        "reconstruction-type": "try",
    }


def test_an_override_replaces_the_one_setting_it_names_and_leaves_the_rest() -> None:
    service = _Service()

    _processor(service).run(PROCESS, _step(override={"rotation-axis": 1630.25}), None)

    assert service.submitted[0].settings == {
        "rotation-axis": 1630.25,
        "energy": 92.0,
        "binning": 0,
    }


def test_an_override_does_not_change_what_the_next_run_naming_the_configuration_gets() -> None:
    service = _Service()
    processor = _processor(service)

    processor.run(PROCESS, _step(override={"rotation-axis": 1630.25}), None)
    processor.run(PROCESS, _step(), None)

    assert service.submitted[1].settings["rotation-axis"] == 1628.5


def test_an_override_of_a_setting_the_configuration_does_not_hold_is_refused() -> None:
    service = _Service()

    with pytest.raises(ProcessRefusedError, match="not a setting the configuration"):
        _processor(service).run(PROCESS, _step(override={"rotation-axes": 1630.25}), None)

    assert service.submitted == []


@pytest.mark.parametrize("override", ["rotation-axis=1630", ["rotation-axis", 1630], 1630])
def test_an_override_that_is_not_a_table_is_refused(override: object) -> None:
    service = _Service()

    with pytest.raises(ProcessRefusedError, match="table of settings"):
        _processor(service).run(PROCESS, _step(override=override), None)

    assert service.submitted == []


@pytest.mark.parametrize("config", ["tomocupy-2bm", "", None])
def test_a_configuration_this_engine_does_not_hold_is_refused(config: object) -> None:
    service = _Service()

    with pytest.raises(ProcessRefusedError, match="not a configuration this engine holds"):
        _processor(service).run(PROCESS, _step(config=config), None)

    assert service.submitted == []


@pytest.mark.parametrize("at", ["19-bm", "", None])
def test_a_place_this_engine_cannot_read_is_refused(at: object) -> None:
    service = _Service()

    with pytest.raises(ProcessRefusedError, match="not a place this engine can read"):
        _processor(service).run(PROCESS, _step(at=at), None)

    assert service.submitted == []


def test_a_step_cannot_name_a_folder_because_the_place_supplies_it() -> None:
    service = _Service()

    with pytest.raises(ProcessRefusedError, match="not a place this engine can read"):
        _processor(service).run(PROCESS, _step(at="/srv/alcf/cora"), None)

    assert service.submitted == []


@pytest.mark.parametrize("parameter", ["input", "output"])
def test_a_path_starting_at_a_root_is_refused_as_not_relative_to_its_place(parameter: str) -> None:
    service = _Service()

    with pytest.raises(ProcessRefusedError, match="relative to its place"):
        _processor(service).run(PROCESS, _step(**{parameter: "/srv/alcf/cora/x/"}), None)

    assert service.submitted == []


@pytest.mark.parametrize("output", ["analysis/scan_0006", "analysis/scan_0006.h5"])
def test_an_output_that_is_not_a_folder_is_refused(output: str) -> None:
    service = _Service()

    with pytest.raises(ProcessRefusedError, match="not a folder"):
        _processor(service).run(PROCESS, _step(output=output), None)

    assert service.submitted == []


@pytest.mark.parametrize("output", ["/analysis/scan_0006/", "../analysis/", "analysis/../../x/"])
def test_an_output_that_could_leave_its_place_is_refused(output: str) -> None:
    service = _Service()

    with pytest.raises(ProcessRefusedError):
        _processor(service).run(PROCESS, _step(output=output), None)

    assert service.submitted == []


PATHS = [
    "scan_0006.h5",
    "Monet/2026-2/scan_0006.h5",
    "Monet/2026-2/",
    "/Monet/scan_0006.h5",
    "..",
    "../other/scan.h5",
    "Monet/../../other/scan.h5",
    "Monet/./scan.h5",
    "Monet//scan.h5",
    "results//",
    "Monet/scan\x00.h5",
    "Monet/scan\n.h5",
    "",
    "   ",
]
"""Paths either side of every clause in the rule, so a clause one copy drops shows here."""


def _refused(attempt: Callable[[], object], refusal: type[Exception]) -> bool:
    try:
        attempt()
    except refusal:
        return True
    return False


@pytest.mark.parametrize("path", PATHS)
def test_a_path_the_mover_refuses_is_a_path_a_process_refuses_and_the_reverse(path: str) -> None:
    moves = _Moves()
    mover = GlobusMove(
        transfers=moves,
        routines=frozenset({"move"}),
        places=Places.parse("19-bm=one:/ alcf=two:/", "19-bm>alcf"),
        poll_interval=0.0,
    )
    processes = _Service()
    processor = _processor(processes)

    mover_refused = _refused(
        lambda: mover.run("move", {"path": path, "from": "19-bm", "to": "alcf"}, None),
        PathRefusedError,
    )
    processor_refused = _refused(
        lambda: processor.run(PROCESS, _step(input=path), None), ProcessRefusedError
    )

    assert mover_refused == processor_refused
    assert len(moves.submitted) == len(processes.submitted) == (0 if mover_refused else 1)


@dataclass
class _Moves:
    """The mover's service, here only so the two path rules can be fed the same paths."""

    submitted: list[tuple[Item, ...]] = field(default_factory=list[tuple[Item, ...]])

    def submit(
        self, *, source: str, destination: str, items: Sequence[Item], label: str | None
    ) -> str:
        self.submitted.append(tuple(items))
        return "task-1"

    def state(self, reference: str) -> Said:
        return Said(SUCCEEDED)


def test_a_routine_this_engine_was_not_told_about_is_declined_rather_than_broken() -> None:
    service = _Service()

    with pytest.raises(UnknownRoutineError) as declined:
        _processor(service).run("tomography_scan", _step(), None)

    assert isinstance(declined.value, RoutineNotRunHereError)
    assert service.submitted == []


def test_a_process_still_going_when_the_bound_runs_out_is_handed_off() -> None:
    service = _Service(says=[Said("running")])

    with pytest.raises(WorkHandedOffError) as handed:
        _processor(service).run(PROCESS, _step(), None)

    assert handed.value.reference == "task-1"


def test_a_process_whose_command_failed_is_refused_with_the_reason_the_far_side_gave() -> None:
    service = _Service(says=[Said(FAILED, "exited 1: no such file")])

    with pytest.raises(ComputeRefusedError, match="no such file"):
        _processor(service).run(PROCESS, _step(), None)


def test_a_process_that_settles_after_a_poll_or_two_is_still_a_run() -> None:
    service = _Service(says=[Said("pending"), Said("running"), Said(SUCCEEDED)])

    ran = _processor(service).run(PROCESS, _step(), None)

    assert ran.said == SUCCEEDED


def test_a_citation_travels_as_the_task_label() -> None:
    service = _Service()
    cites = Citation(execution_id="execution-1", step_id="step-1")

    ran = _processor(service).run(PROCESS, _step(), cites)

    assert service.submitted[0].label == "cora execution-1 step-1"
    assert ran.cites == cites


def test_a_step_with_no_citation_attaches_no_label_rather_than_inventing_one() -> None:
    service = _Service()

    _processor(service).run(PROCESS, _step(), None)

    assert service.submitted[0].label is None


def test_places_are_read_as_names_and_absolute_folders() -> None:
    assert dict(places_from(" alcf=/srv/alcf\n nersc=/srv/nersc ")) == {
        "alcf": "/srv/alcf",
        "nersc": "/srv/nersc",
    }


@pytest.mark.parametrize(
    ("text", "complaint"),
    [
        ("alcf", "name=folder"),
        ("alcf=", "name=folder"),
        ("=/srv/alcf", "not a place name"),
        ("ALCF=/srv/alcf", "not a place name"),
        ("-alcf=/srv/alcf", "not a place name"),
        ("alcf=srv/alcf", "not an absolute folder"),
        ("alcf=/srv/a alcf=/srv/b", "listed twice"),
        ("   ", "no places"),
    ],
)
def test_a_place_setting_that_cannot_be_read_is_refused_when_the_engine_is_built(
    text: str, complaint: str
) -> None:
    with pytest.raises(SettingsError, match=complaint):
        places_from(text)


def test_configurations_are_read_from_their_tables() -> None:
    document = {"config": _configs()}

    configs = configurations_from(document, DERIVED)

    assert sorted(configs) == ["tomocupy-19bm", "tomocupy-try"]
    assert dict(configs["tomocupy-try"]) == {"rotation-axis": 1500.0, "reconstruction-type": "try"}


@pytest.mark.parametrize(
    ("document", "complaint"),
    [
        ({}, "no \\[config.<name>\\] tables"),
        ({"config": {}}, "no \\[config.<name>\\] tables"),
        ({"defaults": {"energy": 92.0}}, "no \\[config.<name>\\] tables"),
        ({"config": {"Tomocupy": {"energy": 92.0}}}, "not a configuration name"),
        ({"config": {"tomocupy": 92.0}}, "not a table of settings"),
        ({"config": {"tomocupy": {}}}, "not a table of settings"),
        ({"config": {"tomocupy": {"file-name": "/srv/a.h5"}}}, "works out from its input"),
        ({"config": {"tomocupy": {"logs-home": "/srv/logs"}}}, "works out from its input"),
    ],
)
def test_a_configurations_file_that_cannot_be_read_is_refused_when_the_engine_is_built(
    document: Mapping[str, object], complaint: str
) -> None:
    with pytest.raises(SettingsError, match=complaint):
        configurations_from(document, DERIVED)
