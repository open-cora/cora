"""What a conductor will start on, and what it does with no engine to run plans.

The loop itself is checked in `test_intake.py` against doubles. What is
left here is the part that turns a file into seams: refusing a
configuration before any hardware moves, and building the acquisition
seam a deployment named.

Nothing below starts the loop. `main` past its configuration checks is
`httpx`, Channel Access and a call that does not return, and every piece
of it is covered somewhere a test can reach.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from conductor.__main__ import NoEngine, NoEngineError, acquisition_for, main
from conductor.claims import Claim
from conductor.conduct import conduct
from conductor.config import ConductorConfig, ConfigError, from_mapping
from conductor.outcomes import Broke, Done
from conductor.procedure import Acquire, Move, Procedure
from tests._fakes import RecordingAcquisition, RecordingControl

if TYPE_CHECKING:
    from pathlib import Path

COMPLETE = """
beamline = "2-bm"

[aroc]
base_url = "https://aroc.example"
token = "a-conductor-token"
"""


def _config(profile: str | None = None) -> ConductorConfig:
    return ConductorConfig(
        beamline="2-bm",
        base_url="https://aroc.example",
        token="t",
        acquisition_profile=profile,
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
    """A conductor that deferred this would refuse the first acquisition of the day.

    By then a beamline has moved motors and is part way through a
    procedure, and the reason is a typo somebody could have been shown
    before anything started.
    """
    path = tmp_path / "conductor.toml"
    path.write_text(f'{COMPLETE}\n[acquisition]\nprofile = "no.such.module:build"\n', "utf-8")

    assert main(["--config", str(path)]) == 2


def test_a_beamline_that_named_no_engine_gets_one_that_refuses() -> None:
    """Not a `None` the loop has to check for.

    An object means everything above here has one shape to handle, and
    the refusal arrives where an engine's own refusal would.
    """
    assert isinstance(acquisition_for(_config()), NoEngine)


def test_an_acquisition_with_no_engine_breaks_that_step_and_not_the_procedure() -> None:
    """The moves around it still run, and the record still says how far it got.

    Refusing the whole assignment at startup would leave a beamline
    unable to run the half of its procedures that move records, which is
    the arrangement `conducting.md` names as the reason conducted work
    does not go through an engine at all.
    """
    control = RecordingControl()
    procedure = Procedure(
        name="two moves and a scan",
        steps=(
            Move(record="2bmb:m1", to=1.0),
            Acquire(plan="tomo_scan", claim=Claim.over("2bmb:cam1:")),
        ),
    )

    walk = conduct(procedure, control=control, acquisition=acquisition_for(_config()))

    assert isinstance(walk.outcomes[0], Done)
    assert control.moves == [("2bmb:m1", 1.0)]
    broke = walk.outcomes[1]
    assert isinstance(broke, Broke)
    assert "NoEngineError" in broke.cause
    assert "tomo_scan" in broke.cause


def test_asking_a_refusing_seam_directly_says_what_to_configure() -> None:
    """The message is read by whoever is on shift, not by a developer."""
    with pytest.raises(NoEngineError) as refusal:
        NoEngine().acquire("tomo_scan", {}, "a-reference")

    assert "[acquisition]" in str(refusal.value)


def test_a_named_profile_is_imported_and_called_to_build_the_seam() -> None:
    """A dotted path, because an engine is an object and not a setting.

    The profile here is one of this suite's own doubles, which is the
    same shape a beamline's startup module has: something importable that
    returns a seam.
    """
    built = acquisition_for(_config("tests._fakes:RecordingAcquisition"))

    assert isinstance(built, RecordingAcquisition)


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
        acquisition_for(_config(profile))

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
                "aroc": {"base_url": "https://a.example", "token": "t"},
                "acquisition": {"profile": "beamline_2bm.startup"},
            }
        )

    assert "module.path:name" in str(problem.value)


def test_an_acquisition_table_that_is_not_a_table_is_refused() -> None:
    with pytest.raises(ConfigError) as problem:
        from_mapping(
            {
                "beamline": "2-bm",
                "aroc": {"base_url": "https://a.example", "token": "t"},
                "acquisition": "beamline_2bm.startup:build",
            }
        )

    assert "acquisition" in str(problem.value)
