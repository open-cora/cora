"""The gate, and the two ways a resolve can be wrong about what is already there.

The gate is the reason this file exists. An unconfirmed procedure is
never sent, and a test that only checked the happy path would pass
against a script that sent every row.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest

from descriptor import ProcedureEntry, ProcedureRegister, RunStep, load_procedures
from seed_procedures import claims, operation_ids, seed

TREE = Path(__file__).parents[1]

_OPERATION = UUID("3f2a91d4-6c18-4b7e-9a05-1d7c8e4b2f60")
_OPERATIONS = {"tomography_scan": _OPERATION}


def _register(beamline: str = "19-bm") -> ProcedureRegister:
    return load_procedures(TREE / beamline / "procedures.toml")


def _narrowed(register: ProcedureRegister, rows: list[ProcedureEntry]) -> ProcedureRegister:
    """The same register with only some of its rows, so one can be driven alone."""
    return ProcedureRegister(beamline=register.beamline, procedures=tuple(rows))


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://keeper.example")


def _empty(request: httpx.Request) -> httpx.Response:
    """A keeper holding no procedure, which refuses any write it is sent."""
    if request.method == "GET":
        return httpx.Response(200, json={"items": [], "next_cursor": None})
    return httpx.Response(500, json={"detail": "this keeper was not meant to be written to"})


def test_an_unconfirmed_procedure_is_not_sent_even_on_a_real_run() -> None:
    """The whole gate. The stub fails any write, so a send would error here."""
    sent: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            sent.append(str(request.url))
            return httpx.Response(500)
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    register = _register()
    drafted = [p for p in register.procedures if not p.confirmed]
    assert drafted, "the register under test holds no unconfirmed row, so this proves nothing"

    with _client(handler) as client:
        gated = _narrowed(register, drafted)
        status = seed(client, gated, _OPERATIONS, dry_run=False)

    assert status == 0
    assert sent == []


def test_a_confirmed_procedure_absent_from_the_keeper_is_defined() -> None:
    posted: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            import json

            posted.append(json.loads(request.content))
            return httpx.Response(201, json={"procedure_id": str(_OPERATION)})
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    register = _register()
    confirmed = [p for p in register.procedures if p.confirmed]
    with _client(handler) as client:
        status = seed(client, _narrowed(register, confirmed), _OPERATIONS, dry_run=False)

    assert status == 0
    assert len(posted) == 1
    assert posted[0]["beamline"] == "19-bm"
    assert posted[0]["steps"][0]["operation_id"] == str(_OPERATION)
    assert posted[0]["steps"][0]["scopes"] == ["corasim19bm:"]


def test_a_dry_run_sends_nothing() -> None:
    with _client(_empty) as client:
        assert seed(client, _register(), _OPERATIONS, dry_run=True) == 0


def test_a_procedure_sharing_a_name_and_claiming_otherwise_is_not_mistaken_for_it() -> None:
    """The flaw the verifier's tests found, in the seeder this time.

    Matching on the name alone would see the drafted row's claims and
    call the confirmed row present, skipping a procedure that is not
    there.
    """
    register = _register()
    drafted = next(p for p in register.procedures if not p.confirmed)
    confirmed = next(p for p in register.procedures if p.confirmed)
    assert drafted.name == confirmed.name, "this test needs the two rows to share a name"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"procedure_id": str(_OPERATION)})
        if request.url.path.startswith("/procedures/"):
            return httpx.Response(
                200,
                json={"steps": [{"kind": "run", "scopes": list(claims(drafted))}]},
            )
        return httpx.Response(
            200,
            json={
                "items": [{"procedure_id": "held", "beamline": "19-bm", "name": drafted.name}],
                "next_cursor": None,
            },
        )

    with _client(handler) as client:
        status = seed(client, _narrowed(register, [confirmed]), _OPERATIONS, dry_run=False)
    assert status == 0


def test_an_operation_nothing_has_defined_stops_the_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    with _client(handler) as client, pytest.raises(LookupError, match="no operation named"):
        operation_ids(client, {"tomography_scan"})


def test_an_operation_defined_twice_stops_the_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "items": [
                    {"operation_id": str(_OPERATION), "name": "tomography_scan"},
                    {"operation_id": str(UUID(int=7)), "name": "tomography_scan"},
                ],
                "next_cursor": None,
            },
        )

    with _client(handler) as client, pytest.raises(LookupError, match="cannot say which identity"):
        operation_ids(client, {"tomography_scan"})


def test_a_claim_is_the_sorted_addresses_a_routine_writes_to() -> None:
    entry = ProcedureEntry(
        name="Tomography scan",
        confirmed=False,
        steps=(RunStep(operation="tomography_scan", scopes=("b:2", "a:1"), parameters={}),),
    )
    assert claims(entry) == ("a:1", "b:2")
