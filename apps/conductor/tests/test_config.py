"""What a conductor will start on, and what it refuses with a reason.

Every refusal here is checked for naming the setting that caused it.
A conductor is started by a service manager at a beamline, where the
only thing anybody sees is one line in a log, and a message saying the
configuration is wrong without saying which part sends whoever is on
shift to read this file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from conductor.config import ConfigError, from_mapping, load

if TYPE_CHECKING:
    from pathlib import Path

COMPLETE = """
beamline = "2-bm"

[aroc]
base_url = "https://keeper.example/"
token = "a-conductor-token"
"""


def test_a_complete_file_gives_the_three_things_a_conductor_needs(tmp_path: Path) -> None:
    path = tmp_path / "conductor.toml"
    path.write_text(COMPLETE, encoding="utf-8")

    config = load(path)

    assert config.beamline == "2-bm"
    assert config.base_url == "https://keeper.example"
    assert config.token == "a-conductor-token"


def test_a_trailing_slash_is_dropped_so_a_path_does_not_double_up() -> None:
    """Every caller of this appends a path that starts with one.

    A base URL kept as written would produce `//executions`, which some
    servers route and some do not, and the ones that do not answer 404
    to a conductor that looks correctly configured.
    """
    config = from_mapping(
        {"beamline": "2-bm", "aroc": {"base_url": "https://keeper.example/", "token": "t"}}
    )

    assert config.base_url == "https://keeper.example"


def test_settings_are_trimmed_so_a_stray_space_is_not_a_different_beamline() -> None:
    """AROC compares a beamline as written, which makes whitespace load-bearing.

    A conductor configured with a trailing space would ask for work at a
    beamline that does not exist and would wait forever without ever
    reporting an error.
    """
    config = from_mapping(
        {"beamline": " 2-bm ", "aroc": {"base_url": "https://keeper.example", "token": " t "}}
    )

    assert config.beamline == "2-bm"
    assert config.token == "t"


@pytest.mark.parametrize(
    ("settings", "named"),
    [
        ({"aroc": {"base_url": "https://a.example", "token": "t"}}, "beamline"),
        ({"beamline": "  ", "aroc": {"base_url": "https://a.example", "token": "t"}}, "beamline"),
        ({"beamline": "2-bm"}, "aroc.base_url"),
        ({"beamline": "2-bm", "aroc": {"token": "t"}}, "aroc.base_url"),
        ({"beamline": "2-bm", "aroc": {"base_url": "https://a.example"}}, "aroc.token"),
        (
            {"beamline": "2-bm", "aroc": {"base_url": "https://a.example", "token": ""}},
            "aroc.token",
        ),
    ],
    ids=[
        "no-beamline",
        "blank-beamline",
        "no-aroc-table",
        "no-base-url",
        "no-token",
        "blank-token",
    ],
)
def test_a_missing_setting_is_refused_by_name(settings: dict[str, object], named: str) -> None:
    with pytest.raises(ConfigError) as problem:
        from_mapping(settings)

    assert named in str(problem.value)


def test_a_base_url_that_is_not_http_is_refused_before_anything_tries_it() -> None:
    """A host with no scheme is the likely typo, and it fails far from here.

    Left alone it becomes `keeper.example/executions`, which a client reads
    as a relative path, so the first symptom is a request to somewhere
    that was never configured.
    """
    with pytest.raises(ConfigError) as problem:
        from_mapping({"beamline": "2-bm", "aroc": {"base_url": "keeper.example", "token": "t"}})

    assert "http" in str(problem.value)


def test_a_file_that_is_not_toml_is_refused_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "conductor.toml"
    path.write_text("beamline = 2-bm\n", encoding="utf-8")

    with pytest.raises(ConfigError) as problem:
        load(path)

    assert str(path) in str(problem.value)


def test_a_file_that_is_not_there_is_refused_naming_the_path(tmp_path: Path) -> None:
    """The commonest startup mistake, and the one worth the clearest message."""
    missing = tmp_path / "nowhere.toml"

    with pytest.raises(ConfigError) as problem:
        load(missing)

    assert str(missing) in str(problem.value)
