"""Working out a setup's schema from the register, and the three things a seeding run may do.

The schema is the half nobody writes, so it is checked against the real
19-BM register as well as against made-up ones. The seeding run is driven
against a keeper that is a mock transport, because what matters is which
writes go out and which do not: a setup the keeper lacks is defined, one it
holds unchanged is left alone, and one that differs is revised against the
revision just read.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from seed_setups import (
    RegisterError,
    idempotency_key,
    load_register,
    seed,
    settings_schema,
    settings_type,
)

TREE = Path(__file__).parents[1]
_PROCESS = UUID("3f2a91d4-6c18-4b7e-9a05-1d7c8e4b2f62")
_SETUP = "5d7c3b1a-2e4f-4a6b-8c9d-0e1f2a3b4c5d"
_SETTINGS: dict[str, Any] = {"rotation-axis": 1628.5, "binning": 0, "minus-log": "True"}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://keeper.example")


def _keeper(
    held: list[dict[str, Any]], now: dict[str, Any] | None = None
) -> tuple[httpx.Client, list[httpx.Request]]:
    """A keeper holding the given listing, answering one setup read, recording every write."""
    writes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/setups":
            return httpx.Response(200, json={"items": held, "next_cursor": None})
        if request.method == "GET" and now is not None:
            return httpx.Response(200, json=now)
        writes.append(request)
        if request.url.path == "/setups":
            return httpx.Response(201, json={"setup_id": _SETUP})
        return httpx.Response(201, json={"setup_id": _SETUP, "revision": 3})

    return _client(handler), writes


def _held(name: str = "tomocupy-19bm") -> dict[str, Any]:
    return {
        "setup_id": _SETUP,
        "beamline": "19-bm",
        "operation_id": str(_PROCESS),
        "name": name,
        "revision": 2,
    }


def _setups(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    chosen = dict(_SETTINGS if settings is None else settings)
    return {"tomocupy-19bm": (chosen, settings_schema("tomocupy-19bm", chosen, {}))}


@pytest.mark.parametrize(
    ("value", "kind"),
    [(True, "boolean"), (0, "integer"), (1628.5, "number"), ("True", "string")],
)
def test_a_settings_type_is_read_off_its_value(value: object, kind: str) -> None:
    assert settings_type("x", value) == kind


@pytest.mark.parametrize("value", [[1, 2], {"a": 1}])
def test_a_setting_that_is_not_a_string_number_or_boolean_is_refused(value: object) -> None:
    with pytest.raises(RegisterError, match="a setting is a string"):
        settings_type("x", value)


def test_a_bound_lands_on_the_setting_it_names_beside_the_type_its_value_gives() -> None:
    unit = {"system": "udunits", "code": "s"}
    bounds = {"ExposureTime": {"minimum": 0.0001, "maximum": 10.0, "unit": unit}}

    schema = settings_schema("tomo", {"ExposureTime": 0.05, "NumAngles": 16}, bounds)

    assert schema["type"] == "object"
    assert schema["properties"] == {
        "ExposureTime": {"type": "number", "minimum": 0.0001, "maximum": 10.0, "unit": unit},
        "NumAngles": {"type": "integer"},
    }


def test_a_bound_for_a_setting_the_setup_holds_no_value_for_is_refused() -> None:
    with pytest.raises(RegisterError, match="holds no value for"):
        settings_schema("tomo", {"NumAngles": 16}, {"NumAngels": {"minimum": 1}})


def test_a_bound_using_a_keyword_the_keeper_refuses_is_refused() -> None:
    with pytest.raises(RegisterError, match="exclusiveMinimum"):
        settings_schema("tomo", {"NumAngles": 16}, {"NumAngles": {"exclusiveMinimum": 0}})


def test_a_register_names_its_operation_by_its_file_name(tmp_path: Path) -> None:
    misnamed = tmp_path / "19-bm" / "setups.toml"
    misnamed.parent.mkdir()
    misnamed.write_text("[config.x]\na = 1\n", encoding="utf-8")

    with pytest.raises(RegisterError, match="is not a setups register"):
        load_register(misnamed)


def test_the_19bm_processing_register_types_every_setting_and_names_its_beamline() -> None:
    beamline, operation, setups = load_register(TREE / "19-bm" / "processing.toml")

    settings, schema = setups["tomocupy-19bm"]
    assert (beamline, operation) == ("19-bm", "process")
    assert set(schema["properties"]) == set(settings)
    assert all("type" in described for described in schema["properties"].values())


def test_the_19bm_collection_register_names_collect_and_carries_its_bounds() -> None:
    beamline, operation, setups = load_register(TREE / "19-bm" / "collection.toml")

    settings, schema = setups["smoke-19bm"]
    described = schema["properties"]
    assert (beamline, operation) == ("19-bm", "collect")
    assert set(described) == set(settings)
    assert described["NumAngles"] == {"type": "integer", "minimum": 1}
    assert described["ExposureTime"]["minimum"] == 0
    assert described["ExposureTime"]["unit"]["code"] == "s"
    assert described["RotationStart"] == {"type": "number"}


def test_a_setup_the_keeper_lacks_is_defined_with_its_worked_out_schema() -> None:
    client, writes = _keeper(held=[])

    status = seed(client, "19-bm", "process", _PROCESS, _setups(), dry_run=False)

    (posted,) = writes
    body = json.loads(posted.content)
    assert status == 0
    assert posted.url.path == "/setups"
    assert body["name"] == "tomocupy-19bm"
    assert body["settings"] == _SETTINGS
    assert body["settings_schema"]["properties"]["binning"] == {"type": "integer"}
    assert posted.headers["Idempotency-Key"] == idempotency_key(
        "19-bm", "process", "tomocupy-19bm", _SETTINGS
    )


def test_a_setup_the_keeper_holds_unchanged_is_left_alone() -> None:
    settings, schema = _setups()["tomocupy-19bm"]
    now = {**_held(), "settings": settings, "settings_schema": schema}
    client, writes = _keeper(held=[_held()], now=now)

    assert seed(client, "19-bm", "process", _PROCESS, _setups(), dry_run=False) == 0
    assert writes == []


def test_a_setup_whose_settings_differ_is_revised_against_the_revision_just_read() -> None:
    older, schema = _setups({**_SETTINGS, "rotation-axis": 1600.0})["tomocupy-19bm"]
    now = {**_held(), "settings": older, "settings_schema": schema}
    client, writes = _keeper(held=[_held()], now=now)

    seed(client, "19-bm", "process", _PROCESS, _setups(), dry_run=False)

    (posted,) = writes
    body = json.loads(posted.content)
    assert posted.url.path == f"/setups/{_SETUP}/revisions"
    assert body["expected_revision"] == 2
    assert body["settings"] == _SETTINGS


def test_a_name_held_by_two_setups_is_reported_and_nothing_is_written() -> None:
    client, writes = _keeper(held=[_held(), {**_held(), "setup_id": "another"}])

    assert seed(client, "19-bm", "process", _PROCESS, _setups(), dry_run=False) == 1
    assert writes == []


def test_a_dry_run_writes_nothing_whatever_it_would_have_done() -> None:
    client, writes = _keeper(held=[])

    assert seed(client, "19-bm", "process", _PROCESS, _setups(), dry_run=True) == 0
    assert writes == []


def test_an_idempotency_key_changes_when_what_it_defines_does() -> None:
    first = idempotency_key("19-bm", "process", "tomocupy-19bm", _SETTINGS)
    edited = idempotency_key("19-bm", "process", "tomocupy-19bm", {**_SETTINGS, "binning": 1})

    assert first == idempotency_key("19-bm", "process", "tomocupy-19bm", dict(_SETTINGS))
    assert first != edited
