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

import httpx

from verify_state import check_devices, check_operations, check_procedures

TREE = Path(__file__).parents[1]


def _client(pages: dict[str, list[dict[str, object]]]) -> httpx.Client:
    """A keeper holding exactly what each listing is given, on one page.

    A request for one procedure is answered out of the same list, because
    the procedure check reads each one's steps after listing them.
    """
    detail = {str(row["procedure_id"]): row for row in pages.get("/procedures", [])}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/procedures/"):
            return httpx.Response(200, json=detail[path.removeprefix("/procedures/")])
        return httpx.Response(200, json={"items": pages.get(path, []), "next_cursor": None})

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


def test_a_keeper_holding_every_written_device_shows_no_gap() -> None:
    with _client({"/devices": _every_registered_device()}) as client:
        assert check_devices(client, TREE).total == 0


def test_a_device_absent_from_the_keeper_is_reported_as_missing() -> None:
    held = [row for row in _every_registered_device() if row["beamline"] != "19-bm"]
    with _client({"/devices": held}) as client:
        gap = check_devices(client, TREE)
    assert len(gap.missing) == 16
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
    held: list[dict[str, object]] = [{"name": "tomography_scan"}, {"name": "tomography_scan"}]
    with _client({"/operations": held}) as client:
        gap = check_operations(client, TREE)
    assert not gap.missing
    assert len(gap.differing) == 1
    assert "cannot say which identity" in gap.differing[0]


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
    drafted = [row for row in _procedure_rows(confirmed=False) if row["beamline"] == "19-bm"]
    with _client({"/procedures": [*_every_confirmed_procedure(), *drafted]}) as client:
        gap = check_procedures(client, TREE)
    assert len(gap.differing) == 1
    assert "is an unconfirmed row and the keeper holds it" in gap.differing[0]
    assert "19bmSoft:aero:m1" in gap.differing[0]


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
    assert len(_every_confirmed_procedure()) == 4
    assert json.dumps(_every_registered_device()[0])
