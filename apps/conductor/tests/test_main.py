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

from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from conductor.__main__ import (
    NoEngine,
    NoEngineError,
    control_for,
    engine_for,
    main,
)
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
from conductor.confinement import Confinement
from conductor.outcomes import Broke, Done
from conductor.procedure import Procedure, Run, Set
from tests._fakes import RecordingAdjusting, RecordingRunning

if TYPE_CHECKING:
    from pathlib import Path

    from conductor.adapters.http_tasking import HttpClient

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
        engine=EngineProfile(profile) if profile else None,
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


def test_a_beamline_that_named_no_engine_gets_one_that_refuses() -> None:
    """Not a `None` the loop has to check for.

    An object means everything above here has one shape to handle, and
    the refusal arrives where an engine's own refusal would.
    """
    assert isinstance(engine_for(_config()), NoEngine)


def test_an_acquisition_with_no_engine_breaks_that_step_and_not_the_procedure() -> None:
    """The moves around it still run, and the record still says how far it got.

    Refusing the whole assignment at startup would leave a beamline
    unable to run the half of its procedures that move records, which is
    the arrangement `conducting.md` names as the reason conducted work
    does not go through an engine at all.
    """
    control = RecordingAdjusting()
    procedure = Procedure(
        name="two moves and a scan",
        steps=(
            Set(record="2bmb:m1", to=1.0),
            Run(routine="tomo_scan", claim=Claim.over("2bmb:cam1:")),
        ),
    )

    walk = conduct(procedure, adjusting=control, running=engine_for(_config()))

    assert isinstance(walk.outcomes[0], Done)
    assert control.moves == [("2bmb:m1", 1.0)]
    broke = walk.outcomes[1]
    assert isinstance(broke, Broke)
    assert "NoEngineError" in broke.cause
    assert "tomo_scan" in broke.cause


def test_asking_a_refusing_seam_directly_says_what_to_configure() -> None:
    """The message is read by whoever is on shift, not by a developer."""
    with pytest.raises(NoEngineError) as refusal:
        NoEngine().run("tomo_scan", {}, None)

    assert "[run]" in str(refusal.value)


def test_a_named_profile_is_imported_and_called_to_build_the_seam() -> None:
    """A dotted path, because an engine is an object and not a setting.

    The profile here is one of this suite's own doubles, which is the
    same shape a beamline's startup module has: something importable that
    returns a seam.
    """
    built = engine_for(_config("tests._fakes:RecordingRunning"))

    assert isinstance(built, RecordingRunning)


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
        engine_for(_config(profile))

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

    assert config.engine == TomoscanServer(
        prefix="corasim2bmb:TomoScan:", routines=frozenset({"tomo_scan"})
    )
    assert isinstance(engine_for(config), TomoscanEngine)


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
        engine_for(config)

    assert "flat_field" in str(refused.value)


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
    control = control_for(_config())

    assert isinstance(control, Confinement)
    assert not control.permits("2bmb:m1")


def test_a_deployment_naming_what_it_may_set_gets_a_seam_confined_to_it() -> None:
    config = replace(_config(), writable=frozenset({Scope.namespace("corasim2bmb:")}))

    control = control_for(config)

    assert isinstance(control, Confinement)
    assert control.permits("corasim2bmb:m1")
    assert not control.permits("2bmb:m1")
