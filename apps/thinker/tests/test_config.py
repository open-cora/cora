"""Loading a configuration, and refusing one that cannot be used."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest

from thinker.config import ConfigError, from_mapping, load

if TYPE_CHECKING:
    from pathlib import Path

WELL_FORMED: dict[str, Any] = {
    "keeper": {"base_url": "https://keeper.example/", "token": "a-token"},
    "inference": {"profile": "somewhere.profiles:build"},
}

FILE = """
[keeper]
base_url = "https://keeper.example"
token = "a-token"

[inference]
profile = "somewhere.profiles:build"
"""


def test_from_mapping_reads_every_field_a_thinker_needs() -> None:
    config = from_mapping(WELL_FORMED)
    assert config.base_url == "https://keeper.example"
    assert config.token == "a-token"
    assert config.inference_profile == "somewhere.profiles:build"


def test_from_mapping_trims_the_trailing_slash_off_a_base_url() -> None:
    """Paths are joined by concatenation, so two slashes would reach nothing."""
    assert from_mapping(WELL_FORMED).base_url == "https://keeper.example"


@pytest.mark.parametrize("missing", ["base_url", "token"])
def test_from_mapping_refuses_a_keeper_table_missing_a_field(missing: str) -> None:
    settings = {"keeper": dict(WELL_FORMED["keeper"]), "inference": WELL_FORMED["inference"]}
    del settings["keeper"][missing]
    with pytest.raises(ConfigError, match=f"keeper.{missing}"):
        from_mapping(settings)


def test_from_mapping_refuses_a_base_url_that_is_not_a_url() -> None:
    settings = {
        "keeper": {"base_url": "keeper.example", "token": "t"},
        "inference": WELL_FORMED["inference"],
    }
    with pytest.raises(ConfigError, match="http or https"):
        from_mapping(settings)


def test_from_mapping_refuses_a_configuration_with_no_inference_table() -> None:
    """A thinker without a provider cannot do the only thing it exists for.

    Unlike `apps/conductor`, whose acquisition seam is optional because a
    beamline that only moves records never reaches one. Every case reaches
    this one.
    """
    with pytest.raises(ConfigError, match="inference table is required"):
        from_mapping({"keeper": WELL_FORMED["keeper"]})


def test_from_mapping_refuses_an_inference_table_that_is_not_a_table() -> None:
    with pytest.raises(ConfigError, match="inference must be a table"):
        from_mapping({"keeper": WELL_FORMED["keeper"], "inference": "somewhere:build"})


def test_from_mapping_refuses_a_profile_that_names_no_attribute() -> None:
    """A message about a missing colon beats an import error naming a non-module."""
    settings = {"keeper": WELL_FORMED["keeper"], "inference": {"profile": "somewhere.profiles"}}
    with pytest.raises(ConfigError, match=re.escape("module.path:name")):
        from_mapping(settings)


def test_from_mapping_names_the_source_in_what_it_refuses() -> None:
    with pytest.raises(ConfigError, match=re.escape("over-there.toml")):
        from_mapping({}, source="over-there.toml")


def test_load_reads_a_file_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "thinker.toml"
    path.write_text(FILE, encoding="utf-8")
    config = load(path)
    assert config.token == "a-token"
    assert config.inference_profile == "somewhere.profiles:build"


def test_load_refuses_a_file_that_is_not_there(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Cannot read"):
        load(tmp_path / "absent.toml")


def test_load_refuses_a_file_that_is_not_toml(tmp_path: Path) -> None:
    path = tmp_path / "thinker.toml"
    path.write_text("this is not = = toml\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load(path)


def test_load_names_the_path_in_what_it_refuses(tmp_path: Path) -> None:
    """A facility running several of these needs to know which file is wrong."""
    path = tmp_path / "thinker.toml"
    path.write_text("[keeper]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=str(path)):
        load(path)
