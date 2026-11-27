"""Defining the facility's operations, and declaring what each drives and names.

Driven against a keeper that is a mock transport, because what matters is
which writes go out: an operation the keeper lacks is defined, a device use
or a place use it has not been told is declared, one it holds the same is
left alone, and one it holds differently is reported and never written over.
"""

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from descriptor import OperationEntry, OperationRegister
from seed_operations import seed

_ID = "01a219b1-ab97-7070-9ae0-a2476ebdebdc"
_SCHEMA: dict[str, Any] = {"type": "object"}


def _register(
    *entries: tuple[str, bool],
    places: tuple[str, ...] = (),
    compute_places: tuple[str, ...] = (),
) -> OperationRegister:
    return OperationRegister(
        operations=tuple(
            OperationEntry(
                name=name,
                parameters_schema=_SCHEMA,
                drives_devices=drives,
                place_parameters=places,
                compute_place_parameters=compute_places,
            )
            for name, drives in entries
        )
    )


def _keeper(
    held: dict[str, dict[str, Any]], *, declaring: int = 204
) -> tuple[httpx.Client, list[httpx.Request]]:
    """A keeper holding these operations by name, recording every write."""
    writes: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            row = held.get(request.url.params.get("name", ""))
            return httpx.Response(200, json={"items": [row] if row else [], "next_cursor": None})
        writes.append(request)
        if request.url.path == "/operations":
            return httpx.Response(201, json={"operation_id": _ID})
        return httpx.Response(declaring)

    return _client(handler), writes


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://keeper.example")


def _held(
    drives_devices: bool | None,
    places: list[str] | None = None,
    compute_places: list[str] | None = None,
) -> dict[str, Any]:
    """A listing row. The place lists default to an empty declaration, so a
    test about device use sees no place-use write."""
    return {
        "operation_id": _ID,
        "name": "move",
        "drives_devices": drives_devices,
        "place_parameters": [] if places is None else places,
        "compute_place_parameters": [] if compute_places is None else compute_places,
    }


def _undeclared_places(row: dict[str, Any]) -> dict[str, Any]:
    return {**row, "place_parameters": None, "compute_place_parameters": None}


def test_a_defined_operation_with_no_device_use_has_the_registers_declared() -> None:
    client, writes = _keeper({"move": _held(None)})

    assert seed(client, _register(("move", False)), dry_run=False) == 0

    (posted,) = writes
    assert posted.url.path == f"/operations/{_ID}/device-use"
    assert json.loads(posted.content) == {"drives_devices": False}


def test_an_operation_the_keeper_lacks_is_defined_and_then_declared() -> None:
    client, writes = _keeper({})

    assert seed(client, _register(("collect", True), places=("at",)), dry_run=False) == 0

    assert [request.url.path for request in writes] == [
        "/operations",
        f"/operations/{_ID}/device-use",
        f"/operations/{_ID}/place-use",
    ]
    assert json.loads(writes[1].content) == {"drives_devices": True}
    assert json.loads(writes[2].content) == {
        "place_parameters": ["at"],
        "compute_place_parameters": [],
    }


def test_a_device_use_the_keeper_already_holds_the_same_is_left_alone() -> None:
    client, writes = _keeper({"move": _held(False)})

    assert seed(client, _register(("move", False)), dry_run=False) == 0
    assert writes == []


def test_a_device_use_the_keeper_holds_differently_is_reported_and_never_written_over(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client, writes = _keeper({"move": _held(True)})

    assert seed(client, _register(("move", False)), dry_run=False) == 1
    assert writes == []
    assert "cannot change" in capsys.readouterr().err


def test_a_declaration_refused_to_a_beamline_token_is_left_for_the_administrator(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client, _ = _keeper({"move": _held(None)}, declaring=403)

    assert seed(client, _register(("move", False)), dry_run=False) == 0
    assert "left for the administrator" in capsys.readouterr().out


def test_a_dry_run_writes_nothing_and_says_what_it_would_declare(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client, writes = _keeper({"move": _held(None)})

    assert seed(client, _register(("move", False), ("collect", True)), dry_run=True) == 0
    assert writes == []
    printed = capsys.readouterr().out
    assert "would declare drives_devices = false" in printed
    assert "would declare drives_devices = true" in printed


def test_a_defined_operation_with_no_place_use_has_the_registers_declared() -> None:
    client, writes = _keeper({"move": _undeclared_places(_held(False))})

    assert seed(client, _register(("move", False), places=("from", "to")), dry_run=False) == 0

    (posted,) = writes
    assert posted.url.path == f"/operations/{_ID}/place-use"
    assert json.loads(posted.content) == {
        "place_parameters": ["from", "to"],
        "compute_place_parameters": [],
    }


def test_a_place_use_the_keeper_already_holds_the_same_is_left_alone() -> None:
    client, writes = _keeper({"move": _held(False, places=["from", "to"])})

    assert seed(client, _register(("move", False), places=("from", "to")), dry_run=False) == 0
    assert writes == []


def test_a_place_use_the_keeper_holds_differently_is_reported_and_never_written_over(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client, writes = _keeper({"move": _held(False, places=["from"])})

    assert seed(client, _register(("move", False), places=("from", "to")), dry_run=False) == 1
    assert writes == []
    captured = capsys.readouterr()
    assert "the keeper holds place_parameters = ['from']" in captured.out
    assert "cannot change" in captured.err


def test_a_place_declaration_refused_to_a_beamline_token_is_left_for_the_administrator(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client, _ = _keeper({"move": _undeclared_places(_held(False))}, declaring=403)

    assert seed(client, _register(("move", False)), dry_run=False) == 0
    assert "not declared; that is the administrator's" in capsys.readouterr().out
