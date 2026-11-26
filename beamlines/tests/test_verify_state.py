"""The three ways a descriptor and a record can disagree, and the one that is a gate.

Each check is driven against a stubbed keeper rather than a live one, for
the reason `test_seed_devices.py` does the same: what is being checked is
how a difference is reported, which does not need a deployment.

The real control for this script is a run against a keeper whose gap is
already known by other means. A stub proves the branches fire; it cannot
prove the comparison is the one an operator needs.
"""

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from descriptor import load_operations
from verify_state import (
    Gap,
    check_devices,
    check_operations,
    check_procedures,
    check_setups,
    report,
)

TREE = Path(__file__).parents[1]


def _every_registered_operation() -> list[dict[str, object]]:
    """Every operation the register holds, as a keeper would list them.

    Read from the register rather than written out, so that adding one
    does not redden a test whose subject is something else. The hand
    written list this replaced named the only operation there was, and
    the second one made it wrong.
    """
    register = load_operations(TREE / "operations.toml")
    return [
        {"name": entry.name, "operation_id": f"op-{entry.name}"} for entry in register.operations
    ]


def _client(pages: dict[str, list[dict[str, object]]]) -> httpx.Client:
    """A keeper holding exactly what each listing is given, on one page.

    A request for one procedure is answered out of the same list, because
    the procedure check reads each one's steps after listing them.

    A row marked retired is listed only to a request that asks for retired
    rows, which is what the keeper does. A check that forgot to ask would
    otherwise be handed them anyway and pass for the wrong reason.
    """
    detail = {str(row["procedure_id"]): row for row in pages.get("/procedures", [])}
    setups = {str(row["setup_id"]): row for row in pages.get("/setups", [])}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/procedures/"):
            return httpx.Response(200, json=detail[path.removeprefix("/procedures/")])
        if path.startswith("/setups/"):
            return httpx.Response(200, json=setups[path.removeprefix("/setups/")])
        rows = pages.get(path, [])
        if request.url.params.get("include_retired") != "true":
            rows = [row for row in rows if row.get("status") != "Retired"]
        return httpx.Response(200, json={"items": rows, "next_cursor": None})

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://keeper.example")


def _device(beamline: str, ref: str, name: str, group: str | None) -> dict[str, object]:
    return {
        "beamline": beamline,
        "external_ref": {"scheme": "epics-record", "value": ref},
        "name": name,
        "group": group,
    }


def _every_registered_device() -> list[dict[str, object]]:
    from descriptor import load

    rows: list[dict[str, object]] = []
    for path in sorted(TREE.glob("*/devices.toml")):
        register = load(path)
        rows.extend(
            _device(register.beamline, entry.ref, entry.name, entry.group)
            for entry in register.devices
        )
    return rows


def _procedure_rows(*, confirmed: bool) -> list[dict[str, object]]:
    """The keeper's two shapes for each descriptor row: a listing and a detail.

    `held_procedures` reads both, so a stub has to serve both.
    """
    from descriptor import RunStep, load_procedures

    rows: list[dict[str, object]] = []
    for path in sorted(TREE.glob("*/procedures.toml")):
        register = load_procedures(path)
        for index, procedure in enumerate(register.procedures):
            if procedure.confirmed is not confirmed:
                continue
            steps = [
                {"kind": "run", "scopes": list(step.scopes)}
                for step in procedure.steps
                if isinstance(step, RunStep)
            ]
            rows.append(
                {
                    "procedure_id": f"{register.beamline}-{index}",
                    "beamline": register.beamline,
                    "name": procedure.name,
                    "steps": steps,
                }
            )
    return rows


def _every_confirmed_procedure() -> list[dict[str, object]]:
    return _procedure_rows(confirmed=True)


def _every_registered_setup() -> list[dict[str, object]]:
    """Every setup the registers hold, as the keeper would serve each at revision 1.

    Listing and detail in one row, because the stub answers both out of it.
    """
    from seed_setups import OPERATIONS_BY_REGISTER, load_register

    rows: list[dict[str, object]] = []
    for register in OPERATIONS_BY_REGISTER:
        for path in sorted(TREE.glob(f"*/{register}")):
            beamline, operation, setups = load_register(path)
            rows.extend(
                {
                    "setup_id": f"{beamline}-{operation}-{name}",
                    "beamline": beamline,
                    "operation_id": f"op-{operation}",
                    "name": name,
                    "revision": 1,
                    "settings": settings,
                    "settings_schema": schema,
                }
                for name, (settings, schema) in setups.items()
            )
    return rows


def _setups_client(setups: list[dict[str, object]]) -> httpx.Client:
    return _client({"/operations": _every_registered_operation(), "/setups": setups})


def test_a_keeper_holding_every_written_device_shows_no_gap() -> None:
    with _client({"/devices": _every_registered_device()}) as client:
        assert check_devices(client, TREE).total == 0


def test_a_device_absent_from_the_keeper_is_reported_as_missing() -> None:
    held = [row for row in _every_registered_device() if row["beamline"] != "19-bm"]
    with _client({"/devices": held}) as client:
        gap = check_devices(client, TREE)
    assert len(gap.missing) == 23
    assert not gap.unexpected


def test_a_device_the_keeper_holds_and_no_register_does_is_reported_as_unexpected() -> None:
    held = [*_every_registered_device(), _device("2-bm", "2bmb:m999", "Invented", None)]
    with _client({"/devices": held}) as client:
        gap = check_devices(client, TREE)
    assert gap.unexpected == ["2-bm 2bmb:m999 (Invented)"]


def test_a_group_changed_after_registration_is_reported_as_differing() -> None:
    """The disagreement no dry run would mention, and Equipment cannot undo."""
    held = _every_registered_device()
    for row in held:
        if row["external_ref"] == {"scheme": "epics-record", "value": "19bmSoft:m23"}:
            row["group"] = "sample-stack"
    with _client({"/devices": held}) as client:
        gap = check_devices(client, TREE)
    assert len(gap.differing) == 1
    assert "sample-base" in gap.differing[0]
    assert "sample-stack" in gap.differing[0]


def test_an_operation_defined_twice_is_reported_even_though_the_name_is_right() -> None:
    held: list[dict[str, object]] = [*_every_registered_operation(), {"name": "tomography_scan"}]
    with _client({"/operations": held}) as client:
        gap = check_operations(client, TREE)
    assert not gap.missing
    assert len(gap.differing) == 1
    assert "cannot say which identity" in gap.differing[0]


def test_a_retired_operation_no_register_names_is_listed_and_not_a_disagreement() -> None:
    """How a register drops a row the record cannot forget."""
    held: list[dict[str, object]] = [
        *_every_registered_operation(),
        {"name": "transfer", "status": "Retired"},
    ]
    with _client({"/operations": held}) as client:
        gap = check_operations(client, TREE)
    assert gap.total == 0
    assert gap.retired == ["transfer"]


def test_a_registered_operation_whose_only_copy_is_retired_is_missing() -> None:
    """A retired row cannot be cited, so it does not stand in for a live one."""
    held: list[dict[str, object]] = [
        {**row, "status": "Retired"} if row["name"] == "move" else row
        for row in _every_registered_operation()
    ]
    with _client({"/operations": held}) as client:
        gap = check_operations(client, TREE)
    assert gap.missing == ["move"]


def test_retiring_the_older_of_two_operations_under_one_name_settles_it() -> None:
    held: list[dict[str, object]] = [
        *_every_registered_operation(),
        {"name": "tomography_scan", "status": "Retired"},
    ]
    with _client({"/operations": held}) as client:
        gap = check_operations(client, TREE)
    assert gap.total == 0
    assert gap.retired == ["tomography_scan"]


def test_a_keeper_holding_every_confirmed_procedure_shows_no_gap() -> None:
    with _client({"/procedures": _every_confirmed_procedure()}) as client:
        assert check_procedures(client, TREE).total == 0


def test_an_unconfirmed_procedure_found_in_the_keeper_is_reported_as_differing() -> None:
    """The gate, stated as a test.

    An unconfirmed procedure is never seeded, so one in the record means
    the gate was bypassed and a drafted routine over real records is
    dispatchable. It is reported as a disagreement rather than as an
    extra, because an extra reads as untidy and this is not.
    """
    drafted = [
        row
        for row in _procedure_rows(confirmed=False)
        if row["beamline"] == "19-bm" and row["name"] == "Tomography scan"
    ]
    with _client({"/procedures": [*_every_confirmed_procedure(), *drafted]}) as client:
        gap = check_procedures(client, TREE)
    assert len(gap.differing) == 1
    assert "is an unconfirmed row and the keeper holds it" in gap.differing[0]
    assert "19bmSoft:aero:m1" in gap.differing[0]


def _a_retired_procedure(name: str, *scopes: str) -> dict[str, object]:
    return {
        "procedure_id": f"retired-{name}",
        "beamline": "19-bm",
        "name": name,
        "status": "Retired",
        "steps": [{"kind": "run", "scopes": list(scopes)}],
    }


def test_a_retired_procedure_no_register_names_is_listed_and_not_a_disagreement() -> None:
    retired = _a_retired_procedure("Move a dataset to the computing facility")
    with _client({"/procedures": [*_every_confirmed_procedure(), retired]}) as client:
        gap = check_procedures(client, TREE)
    assert gap.total == 0
    assert gap.retired == ["19-bm 'Move a dataset to the computing facility'"]


def test_a_retired_copy_of_an_unconfirmed_procedure_breaches_no_gate() -> None:
    """The gate keeps a drafted routine over real records from being
    dispatchable. A retired copy cannot be dispatched, so it is listed and
    is not the disagreement an active copy would be."""
    retired = _a_retired_procedure("Tomography scan", "19bmSoft:aero:m1")
    with _client({"/procedures": [*_every_confirmed_procedure(), retired]}) as client:
        gap = check_procedures(client, TREE)
    assert gap.total == 0
    assert gap.retired == ["19-bm 'Tomography scan'"]


def test_a_confirmed_procedure_whose_only_copy_is_retired_is_missing() -> None:
    held = [
        {**row, "status": "Retired"}
        if row["beamline"] == "19-bm" and row["name"] == "Tomography scan"
        else row
        for row in _every_confirmed_procedure()
    ]
    with _client({"/procedures": held}) as client:
        gap = check_procedures(client, TREE)
    assert gap.missing == ["19-bm 'Tomography scan' over corasim19bm:"]
    assert gap.retired == ["19-bm 'Tomography scan'"]


def test_a_keeper_holding_every_written_setup_shows_no_gap() -> None:
    with _setups_client(_every_registered_setup()) as client:
        assert check_setups(client, TREE).total == 0


def test_a_setup_absent_from_the_keeper_is_reported_as_missing() -> None:
    held = [row for row in _every_registered_setup() if row["name"] != "smoke-19bm"]
    with _setups_client(held) as client:
        gap = check_setups(client, TREE)
    assert gap.missing == ["19-bm collect smoke-19bm"]
    assert not gap.unexpected


def test_a_setup_the_keeper_holds_and_no_register_does_is_reported_as_unexpected() -> None:
    invented = {**_every_registered_setup()[0], "setup_id": "invented", "name": "invented-19bm"}
    with _setups_client([*_every_registered_setup(), invented]) as client:
        gap = check_setups(client, TREE)
    assert len(gap.unexpected) == 1
    assert gap.unexpected[0].endswith(" invented-19bm")


def test_a_setup_revised_away_from_its_register_is_differing_and_names_the_setting() -> None:
    held = _every_registered_setup()
    for row in held:
        if row["name"] == "smoke-19bm":
            row["settings"] = {**cast("dict[str, object]", row["settings"]), "NumAngles": 64}
            row["revision"] = 2
    with _setups_client(held) as client:
        gap = check_setups(client, TREE)
    assert gap.differing == [
        "19-bm collect smoke-19bm settings: the register and revision 2 differ in NumAngles"
    ]


def test_a_setup_whose_schema_was_revised_alone_is_differing() -> None:
    held = _every_registered_setup()
    for row in held:
        if row["name"] == "smoke-19bm":
            schema = cast("dict[str, object]", row["settings_schema"])
            row["settings_schema"] = {**schema, "required": ["NumAngles"]}
    with _setups_client(held) as client:
        gap = check_setups(client, TREE)
    assert len(gap.differing) == 1
    assert "smoke-19bm schema" in gap.differing[0]


def test_a_name_two_setups_share_is_reported_and_neither_is_read() -> None:
    first = next(row for row in _every_registered_setup() if row["name"] == "smoke-19bm")
    twin: dict[str, object] = {**first, "setup_id": "twin", "settings": {}}
    with _setups_client([*_every_registered_setup(), twin]) as client:
        gap = check_setups(client, TREE)
    assert len(gap.differing) == 1
    assert "2 setups share this name" in gap.differing[0]


def test_a_surface_that_agrees_still_names_what_it_holds_retired(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report(Gap("operations", retired=["transfer"]))
    printed = capsys.readouterr().out
    assert "operations: agrees" in printed
    assert "retired in the keeper, which no descriptor needs to name: 1" in printed
    assert "transfer" in printed


def test_a_listing_longer_than_one_page_is_walked_to_its_end() -> None:
    """A first page is not an answer, and a check that stopped there would
    report every later row as missing."""
    rows: list[dict[str, object]] = _every_registered_device()
    half = len(rows) // 2

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "second":
            return httpx.Response(200, json={"items": rows[half:], "next_cursor": None})
        return httpx.Response(200, json={"items": rows[:half], "next_cursor": "second"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="https://keeper.example") as client:
        assert check_devices(client, TREE).total == 0


def test_the_stub_is_built_from_the_registers_it_is_compared_against() -> None:
    """A guard on the fixtures, not on the script.

    Every no-gap test above builds the keeper's side out of the same files
    it then compares against, so an empty register would make all of them
    pass while comparing nothing.
    """
    assert len(_every_registered_device()) >= 90
    assert len(_every_confirmed_procedure()) == 7
    assert len(_every_registered_setup()) == 2
    assert json.dumps(_every_registered_device()[0])
