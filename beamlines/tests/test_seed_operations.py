"""Defining the facility's operations, and declaring whether each drives equipment.

Driven against a keeper that is a mock transport, because what matters is
which writes go out: an operation the keeper lacks is defined, a device use
it has not been told is declared, one it holds the same is left alone, and
one it holds differently is reported and never written over.
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


def _register(*entries: tuple[str, bool]) -> OperationRegister:
    return OperationRegister(
        operations=tuple(
            OperationEntry(name=name, parameters_schema=_SCHEMA, drives_devices=drives)
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


def _held(drives_devices: bool | None) -> dict[str, Any]:
    return {"operation_id": _ID, "name": "move", "drives_devices": drives_devices}


def test_a_defined_operation_with_no_device_use_has_the_registers_declared() -> None:
    client, writes = _keeper({"move": _held(None)})

    assert seed(client, _register(("move", False)), dry_run=False) == 0

    (posted,) = writes
    assert posted.url.path == f"/operations/{_ID}/device-use"
    assert json.loads(posted.content) == {"drives_devices": False}


def test_an_operation_the_keeper_lacks_is_defined_and_then_declared() -> None:
    client, writes = _keeper({})

    assert seed(client, _register(("collect", True)), dry_run=False) == 0

    assert [request.url.path for request in writes] == [
        "/operations",
        f"/operations/{_ID}/device-use",
    ]
    assert json.loads(writes[1].content) == {"drives_devices": True}


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
