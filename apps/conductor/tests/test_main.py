"""What a conductor will start on, and what it does with no engine to run plans.

The loop itself is checked in `test_intake.py` against doubles. What is
left here is the part that turns a file into seams: refusing a
configuration before any hardware moves, and building the run
seam a deployment named.

Nothing below starts the loop. `main` past its configuration checks is
`httpx`, Channel Access and a call that does not return, and every piece
of it is covered somewhere a test can reach.
"""

from __future__ import annotations

import os
import signal
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from conductor.__main__ import (
    main,
    repertoire_for,
    stop_on_termination,
)
from conductor.adapters.epics_control import EpicsControl
from conductor.adapters.tomoscan_engine import ManyRoutinesError, TomoscanEngine
from conductor.claims import Claim, Scope
from conductor.conduct import conduct
from conductor.config import (
    ConductorConfig,
    ConfigError,
    EngineProfile,
    TomoscanServer,
    from_mapping,
)
from conductor.intake import serve
from conductor.outcomes import Declined, Done
from conductor.procedure import RECORD_PARAMETER, SET_ROUTINE, Procedure, Step
from conductor.repertoire import Repertoire, RoutineClaimedTwiceError
from conductor.seams import Assignment, Citation, Ran, RoutineNotRunHereError
from tests._fakes import RecordingControl, RecordingRunning, repertoire_of

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from conductor.adapters.http_tasking import HttpClient
    from conductor.seams import Running, Tasking

COMPLETE = """
beamline = "2-bm"

[keeper]
base_url = "https://keeper.example"
token = "a-conductor-token"
"""


FAKE_HTTP = cast("HttpClient", object())
"""Something to hold, never called. Building a filer sends no request."""


def _config(profile: str | None = None) -> ConductorConfig:
    return ConductorConfig(
        beamline="2-bm",
        base_url="https://keeper.example",
        token="t",
        engines=(EngineProfile(profile=profile, routines=frozenset({"tomo_scan"})),)
        if profile
        else (),
    )


def test_a_configuration_that_cannot_be_read_stops_before_anything_is_built(
    tmp_path: Path,
) -> None:
    """Exit 2 and a line naming the file, which is all a service manager shows."""
    status = main(["--config", str(tmp_path / "nowhere.toml")])

    assert status == 2


def test_a_profile_that_will_not_import_stops_at_startup_rather_than_mid_procedure(
    tmp_path: Path,
) -> None:
    """A conductor that deferred this would refuse the first run of the day.

    By then a beamline has moved motors and is part way through a
    procedure, and the reason is a typo somebody could have been shown
    before anything started.
    """
    path = tmp_path / "conductor.toml"
    path.write_text(f'{COMPLETE}\n[run]\nprofile = "no.such.module:build"\n', "utf-8")

    assert main(["--config", str(path)]) == 2


def test_a_beamline_that_named_no_engine_still_runs_the_one_routine_every_beamline_has() -> None:
    """Writing a record is a routine like any other, so it is always in the table."""
    assert repertoire_for(_config()).runs == frozenset({SET_ROUTINE})


def test_an_acquisition_with_no_engine_is_declined_and_not_filed_as_a_fault() -> None:
    """The sets around it still run, and the record still says how far it got.

    Declined rather than broken, because a beamline that configured no
    acquisition engine has not failed at anything when it is asked for a
    scan. Filing that as a fault is what `outcomes` introduced `Declined`
    to stop, and the no-engine case went on doing it until every routine
    went through one table.
    """
    procedure = Procedure(
        name="two moves and a scan",
        steps=(
            Step.setting(record="2bmb:m1", value=1.0),
            Step(routine="tomo_scan", claim=Claim.over("2bmb:cam1:")),
        ),
    )

    control = RecordingControl()
    walk = conduct(procedure, running=Repertoire.of((frozenset({SET_ROUTINE}), control)))

    assert isinstance(walk.outcomes[0], Done)
    assert control.moves == [("2bmb:m1", 1.0)]
    declined = walk.outcomes[1]
    assert isinstance(declined, Declined)
    assert declined.routine == "tomo_scan"


def test_asking_for_a_routine_nothing_runs_says_what_this_conductor_does_run() -> None:
    """The message is read by whoever is on shift, not by a developer."""
    with pytest.raises(RoutineNotRunHereError) as refusal:
        repertoire_for(_config()).run("tomo_scan", {}, None)

    assert SET_ROUTINE in str(refusal.value)


def test_a_named_profile_is_imported_and_called_to_build_the_seam() -> None:
    """A dotted path, because an engine is an object and not a setting.

    The profile here is one of this suite's own doubles, which is the
    same shape a beamline's startup module has: something importable that
    returns a seam.
    """
    built = repertoire_for(_config("tests._fakes:RecordingRunning"))

    assert isinstance(built.engines["tomo_scan"], RecordingRunning)


@pytest.mark.parametrize(
    ("profile", "named"),
    [
        ("no.such.module:build", "no.such.module"),
        ("conductor.intake:nothing_by_this_name", "nothing_by_this_name"),
        ("conductor.intake:DEFAULT_WAIT_SECONDS", "DEFAULT_WAIT_SECONDS"),
    ],
    ids=["no-module", "no-attribute", "not-callable"],
)
def test_a_profile_that_cannot_build_a_seam_is_refused_by_name(profile: str, named: str) -> None:
    with pytest.raises(ConfigError) as problem:
        repertoire_for(_config(profile))

    assert named in str(problem.value)


def test_a_profile_missing_its_separator_is_refused_where_the_format_is_known() -> None:
    """An import of it would report a module that was never a module.

    The string names two things, and a message about the first one alone
    sends whoever reads it looking for a file that does not exist.
    """
    with pytest.raises(ConfigError) as problem:
        from_mapping(
            {
                "beamline": "2-bm",
                "keeper": {"base_url": "https://a.example", "token": "t"},
                "run": {"profile": "beamline_2bm.startup"},
            }
        )

    assert "module.path:name" in str(problem.value)


def test_a_run_table_naming_a_prefix_builds_a_tomoscan_seam_with_no_deployment_code() -> None:
    """Everything that engine takes is a string, so no profile is needed.

    The point of the second shape: a beamline running TomoScan writes
    two settings rather than authoring a Python file that nothing in
    this tree would test.
    """
    config = from_mapping(
        {
            "beamline": "2-bm",
            "keeper": {"base_url": "https://a.example", "token": "t"},
            "run": {"prefix": "corasim2bmb:TomoScan:", "routines": ["tomo_scan"]},
        }
    )

    assert config.engines == (
        TomoscanServer(prefix="corasim2bmb:TomoScan:", routines=frozenset({"tomo_scan"})),
    )
    assert isinstance(repertoire_for(config).engines["tomo_scan"], TomoscanEngine)


def test_a_configured_scan_timeout_reaches_the_engine_that_waits() -> None:
    """The bound a beamline writes is the bound its scan is given.

    Parsed and then dropped is the shape this is guarding: the config
    carried the number and the engine kept its own, so a station that
    had said what its longest scan was still waited the default and
    still recorded a scan it was happily taking as broken.
    """
    config = from_mapping(
        {
            "beamline": "2-bm",
            "keeper": {"base_url": "https://a.example", "token": "t"},
            "run": {
                "prefix": "corasim2bmb:TomoScan:",
                "routines": ["tomo_scan"],
                "scan_timeout": 28800,
            },
        }
    )

    engine = repertoire_for(config).engines["tomo_scan"]

    assert isinstance(engine, TomoscanEngine)
    assert engine.scan_timeout == 28800.0


def test_a_run_table_with_no_scan_timeout_leaves_the_engine_its_default() -> None:
    config = from_mapping(
        {
            "beamline": "2-bm",
            "keeper": {"base_url": "https://a.example", "token": "t"},
            "run": {"prefix": "corasim2bmb:TomoScan:", "routines": ["tomo_scan"]},
        }
    )

    engine = repertoire_for(config).engines["tomo_scan"]

    assert isinstance(engine, TomoscanEngine)
    assert engine.scan_timeout == TomoscanEngine(prefix="x:", routines=frozenset()).scan_timeout


def test_a_tomoscan_engine_named_two_routines_refuses_to_be_built() -> None:
    """The allowlist is a guard, not a selector, so widening it disarms it.

    A name picks nothing here: TomoScan performs one kind of scan and
    what varies is the parameters. So a second name would be accepted
    and would start that same scan, which is exactly the outcome the
    one-name check exists to prevent. The config parses, because it is
    well formed; the engine is what cannot be built from it.
    """
    config = from_mapping(
        {
            "beamline": "2-bm",
            "keeper": {"base_url": "https://a.example", "token": "t"},
            "run": {"prefix": "corasim2bmb:TomoScan:", "routines": ["tomo_scan", "flat_field"]},
        }
    )

    with pytest.raises(ManyRoutinesError) as refused:
        repertoire_for(config)

    assert "flat_field" in str(refused.value)


def test_two_run_tables_put_both_engines_behind_one_seam() -> None:
    """The arrangement work that crosses a boundary needs.

    A scan is handed to an acquisition server at the beamline and the
    file it wrote is moved by something that has never heard of Channel
    Access, and one procedure reaches both. The core could already do
    this: `Repertoire` picks by routine and takes as many engines as it
    is given. What could not say it was the configuration.
    """
    config = from_mapping(
        {
            "beamline": "2-bm",
            "keeper": {"base_url": "https://a.example", "token": "t"},
            "run": [
                {"prefix": "corasim2bmb:TomoScan:", "routines": ["tomo_scan"]},
                {"profile": "tests._fakes:RecordingRunning", "routines": ["transfer"]},
            ],
        }
    )

    built = repertoire_for(config)

    assert isinstance(built.engines["tomo_scan"], TomoscanEngine)
    assert isinstance(built.engines["transfer"], RecordingRunning)
    assert built.runs == frozenset({SET_ROUTINE, "tomo_scan", "transfer"})


def test_two_run_tables_offering_one_routine_are_refused_before_any_step_reaches_them() -> None:
    """Order would otherwise decide, and be correct by accident until it changed."""
    config = from_mapping(
        {
            "beamline": "2-bm",
            "keeper": {"base_url": "https://a.example", "token": "t"},
            "run": [
                {"prefix": "corasim2bmb:TomoScan:", "routines": ["tomo_scan"]},
                {"profile": "tests._fakes:RecordingRunning", "routines": ["tomo_scan"]},
            ],
        }
    )

    with pytest.raises(RoutineClaimedTwiceError) as refused:
        repertoire_for(config)

    assert "tomo_scan" in str(refused.value)


def test_an_empty_list_of_run_tables_is_refused_rather_than_read_as_no_engine() -> None:
    """Writing one is asking for an engine, so silence would decline every run."""
    with pytest.raises(ConfigError) as problem:
        from_mapping(
            {
                "beamline": "2-bm",
                "keeper": {"base_url": "https://a.example", "token": "t"},
                "run": [],
            }
        )

    assert "empty list" in str(problem.value)


def test_a_run_table_naming_both_a_profile_and_a_prefix_is_refused() -> None:
    """Two engines named, and picking one silently would pick wrong half the time."""
    with pytest.raises(ConfigError) as problem:
        from_mapping(
            {
                "beamline": "2-bm",
                "keeper": {"base_url": "https://a.example", "token": "t"},
                "run": {"profile": "a:b", "prefix": "x:", "routines": ["s"]},
            }
        )

    assert "one or the" in str(problem.value)


def test_a_run_table_naming_neither_is_refused_with_both_shapes_spelled_out() -> None:
    """A present table is a request for an engine, so an empty one is a mistake.

    Distinct from leaving the table out, which is the supported way to
    have no engine and is what 2-BM runs today.
    """
    with pytest.raises(ConfigError) as problem:
        from_mapping(
            {
                "beamline": "2-bm",
                "keeper": {"base_url": "https://a.example", "token": "t"},
                "run": {},
            }
        )

    assert "profile" in str(problem.value)
    assert "prefix" in str(problem.value)


@pytest.mark.parametrize(
    ("routines", "because"),
    [
        (None, "missing"),
        ([], "empty"),
        (["tomo_scan", ""], "an empty name"),
        (["tomo_scan", 7], "a name that is not a string"),
    ],
    ids=["missing", "empty", "empty-name", "not-a-string"],
)
def test_a_tomoscan_table_without_usable_routine_names_is_refused(
    routines: object, because: str
) -> None:
    """A server told to answer to nothing refuses every run while looking configured."""
    table: dict[str, object] = {"prefix": "corasim2bmb:TomoScan:"}
    if routines is not None:
        table["routines"] = routines

    with pytest.raises(ConfigError, match="routines"):
        from_mapping(
            {
                "beamline": "2-bm",
                "keeper": {"base_url": "https://a.example", "token": "t"},
                "run": table,
            }
        )


def test_an_acquisition_table_that_is_not_a_table_is_refused() -> None:
    with pytest.raises(ConfigError) as problem:
        from_mapping(
            {
                "beamline": "2-bm",
                "keeper": {"base_url": "https://a.example", "token": "t"},
                "run": "beamline_2bm.startup:build",
            }
        )

    assert "run" in str(problem.value)


def test_a_deployment_naming_nothing_writable_gets_a_seam_that_sets_nothing() -> None:
    """The default is the strictest policy, not the absence of one."""
    control = repertoire_for(_config()).engines[SET_ROUTINE]

    assert isinstance(control, EpicsControl)
    assert not control.permits("2bmb:m1")


def test_a_deployment_naming_what_it_may_set_gets_a_seam_confined_to_it() -> None:
    config = replace(_config(), writable=frozenset({Scope.namespace("corasim2bmb:")}))

    control = repertoire_for(config).engines[SET_ROUTINE]

    assert isinstance(control, EpicsControl)
    assert control.permits("corasim2bmb:m1")
    assert not control.permits("2bmb:m1")


def test_a_stop_signal_lets_the_walk_in_progress_finish_and_report() -> None:
    """The orderly stop the loop's predicate exists for.

    The handler used to raise instead. A `KeyboardInterrupt` is a
    `BaseException`, so neither the loop's arm nor `conduct`'s caught
    one: a signal landing mid-walk unwound through the running step,
    left the motor where that step had got to, reported none of the
    steps after it, and sent no ending. Driven by a real signal, because
    a double raising where one would land is what that failure was made
    of.

    The predicate is capped as well as signalled, so a handler that
    stops nothing fails this on its assertions rather than hanging the
    suite.
    """
    moved: list[str] = []
    reported: list[tuple[object, str]] = []

    class StopsUsMidWalk:
        def run(self, routine: str, parameters: Mapping[str, object], cites: Citation | None):
            _ = routine
            record = str(parameters[RECORD_PARAMETER])
            if record == "2bmb:m2":
                os.kill(os.getpid(), signal.SIGTERM)
            moved.append(record)
            return Ran(cites=cites, engine_reference=None, said="arrived")

    class Reports:
        def step_ended(self, index: int, outcome: object) -> None:
            reported.append((index, type(outcome).__name__))

        def walk_ended(self) -> None:
            reported.append(("end", "walk_ended"))

    procedure = Procedure(
        name="three_sets",
        steps=(
            Step.setting(record="2bmb:m1", value=1.0),
            Step.setting(record="2bmb:m2", value=2.0),
            Step.setting(record="2bmb:m3", value=3.0),
        ),
    )

    class HandsOverOne:
        def take(self, beamline: str, runs: frozenset[str], wait: float) -> Assignment:
            _ = beamline, runs, wait
            return Assignment(execution_id="e1", procedure=procedure, step_ids=["a", "b", "c"])

        def claim(self, execution_id: str) -> Reports:
            _ = execution_id
            return Reports()

    asked_to_stop = stop_on_termination()
    turns = iter(range(2))

    def keep_going() -> bool:
        return asked_to_stop() and next(turns, None) is not None

    before = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        serve(
            cast("Tasking", HandsOverOne()),
            "2-bm",
            running=repertoire_of(cast("Running", StopsUsMidWalk()), RecordingRunning()),
            runs=frozenset({"tomo_scan"}),
            keep_going=keep_going,
            pause=lambda _seconds: None,
            note=lambda _message: None,
        )
    finally:
        for number, handler in before.items():
            signal.signal(number, handler)

    assert moved == ["2bmb:m1", "2bmb:m2", "2bmb:m3"], "the walk ran to its last step"
    assert reported == [(0, "Done"), (1, "Done"), (2, "Done"), ("end", "walk_ended")]
