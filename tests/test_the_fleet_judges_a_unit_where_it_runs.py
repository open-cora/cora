"""The fleet page's fold, which is where every judgement on that page is made.

`tools/cora_fleet.py` is threads, ssh, an HTTP server and a page, and the
page colours what the fold returns and decides nothing itself. So the fold
is the part worth a test, and the cases below are the ones where the
obvious reading is the wrong one.

## Why these cases

A unit's enablement is one answer for a whole account and its running state
is one answer per host, so a simulator pinned to the IOC host reads as
stopped from the conductor's host while it serves. A host that does not
answer has said nothing, which is neither healthy nor down. An execution
waiting for a routine no engine at its beamline runs is returned to no
conductor and waits forever while every service reads healthy.

The later cases come from one afternoon at the facility. The keeper had not
run for two weeks, every conductor read active under systemd while its
keeper refused it every five seconds, and the first version of this page
showed all of it as grey. A page that can be fooled that way is worse than
no page, because somebody stops looking.

The host names are placeholders. A real one would be a facility coordinate,
which this tier refuses in a tracked file.
"""

from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    import threading

TREE_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = TREE_ROOT / "tools" / "cora_fleet.py"
NOW = 1_800_000_000.0
MINIMUM_TEMPLATES = 8
"""How few unit templates the kind check may find before it ranges over too little."""


def _fleet() -> Any:
    """Load the page, which ships as a script to run rather than a module."""
    spec = importlib.util.spec_from_file_location("_cora_fleet_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


FLEET = _fleet()
PROBE = sys.modules["verify_hosts"]
"""The host probe the page imported, whose report types the cases below build."""
TREE = FLEET.read_tree(TREE_ROOT / "beamlines")


def _book(*slugs: str) -> Any:
    return FLEET.Book(
        targets={slug: FLEET.Target("conductor-host", "acct") for slug in slugs},
        central_host="central-host",
    )


def _reach(said: str = "200", exit_code: int = 0) -> Any:
    return PROBE.KeeperReach(url="https://keeper.example:8443", exit=exit_code, said=said)


REFUSED = ("curl: (7) Failed to connect to keeper.example port 8443: Connection refused000", 7)


def _answer(
    units: list[Any],
    elsewhere: dict[str, tuple[str, str, str]] | None = None,
    *,
    unreachable: str | None = None,
    revision: str = "abc1234",
    routines: tuple[str, ...] = ("tomography_scan",),
    keeper: Any = None,
    errors: int | None = 0,
    uptime: int | None = 3600,
    simulated: str = "",
    pinned: dict[str, dict[str, Any]] | None = None,
) -> Any:
    report = FLEET.HostReport(
        beamline="19-bm",
        target="acct@conductor-host",
        revisions={"conductor": revision, "reporter": revision},
        unreachable=unreachable,
        units=units,
        engines=[PROBE.Engine(profile="", prefix="corasim19bm:TomoScan:", routines=routines)],
        keeper=keeper if keeper is not None else _reach(),
        errors=errors,
        uptime=uptime,
        simulated=simulated,
    )
    return FLEET.HostAnswer(report, NOW, 1.0, elsewhere or {}, pinned or {})


def _conductor() -> Any:
    return FLEET.Unit("cora-conductor.service", "enabled", "active", "conductor-host")


def _reporter() -> Any:
    return FLEET.Unit("cora-reporter.service", "enabled", "active", "conductor-host")


def _simulator() -> Any:
    return FLEET.Unit("cora-tomoscan-sim.service", "enabled", "inactive", "ioc-host")


def _card(state: dict[str, Any], slug: str = "19-bm") -> dict[str, Any]:
    return next(card for card in state["beamlines"] if card["slug"] == slug)


def _part(card: dict[str, Any], part_id: str) -> dict[str, Any]:
    return next(part for part in card["parts"] if part["id"] == part_id)


def _execution(status: str, routines: list[str], seconds_ago: float) -> dict[str, Any]:
    stamp = datetime.fromtimestamp(NOW - seconds_ago, UTC).isoformat()
    return {
        "procedure_name": f"{status} for {'+'.join(routines)}",
        "status": status,
        "routines": routines,
        "step_count": 1,
        "reported_count": 0,
        "created_at": stamp,
        "updated_at": stamp,
    }


def _keeper(*executions: dict[str, Any]) -> Any:
    return FLEET.KeeperAnswer(
        asked_at=NOW,
        url="https://keeper.example",
        version="1",
        ready="ready",
        executions={"19-bm": list(executions)},
        unfiled={"19-bm": []},
    )


def _fold(hosts: dict[str, Any], keeper: Any = None, **kwargs: Any) -> dict[str, Any]:
    slugs = sorted(hosts) or ["19-bm"]
    return FLEET.fold(TREE, _book(*slugs), hosts, None, keeper, now=NOW, **kwargs)


def test_a_unit_pinned_to_another_host_is_judged_by_that_hosts_answer() -> None:
    serving = {"cora-tomoscan-sim.service": ("ioc-host", "active", "")}
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter(), _simulator()], serving)}))

    simulator = _part(card, "cora-tomoscan-sim")
    assert simulator["health"] == "healthy"
    assert "ioc-host" in simulator["where"]


def test_a_unit_stopped_on_the_host_it_is_pinned_to_is_down_where_it_is_pinned() -> None:
    stopped = {"cora-tomoscan-sim.service": ("ioc-host", "failed", "")}
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter(), _simulator()], stopped)}))

    simulator = _part(card, "cora-tomoscan-sim")
    assert simulator["health"] == "down"
    assert "ioc-host" in simulator["where"]


def test_a_unit_whose_host_could_not_be_asked_is_unknown_rather_than_down() -> None:
    unasked = {"cora-tomoscan-sim.service": ("ioc-host", "unasked", "Connection timed out")}
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter(), _simulator()], unasked)}))

    assert _part(card, "cora-tomoscan-sim")["health"] == "unknown"
    assert all(part["health"] != "down" for part in card["parts"])


def test_a_conductor_host_that_cannot_be_asked_is_unknown_and_says_why() -> None:
    card = _card(_fold({"19-bm": _answer([], unreachable="Connection timed out")}))

    conductor = _part(card, "cora-conductor")
    assert conductor["health"] == "unknown"
    assert "Connection timed out" in conductor["cause"]["text"]


def test_an_account_holding_units_but_no_conductor_is_down_at_the_conductor() -> None:
    serving = {"cora-tomoscan-sim.service": ("ioc-host", "active", "")}
    card = _card(_fold({"19-bm": _answer([_reporter(), _simulator()], serving)}))

    conductor = _part(card, "cora-conductor")
    assert conductor["health"] == "down"
    assert "no conductor unit" in conductor["cause"]["text"]


def test_an_execution_waiting_for_a_routine_no_engine_here_runs_is_a_fault() -> None:
    keeper = _keeper(
        _execution("Dispatched", ["transfer"], 60),
        _execution("Dispatched", ["tomography_scan"], 60),
    )
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter()])}, keeper))

    faults = [f["text"] for f in card["findings"] if f["level"] == "fault"]
    assert len(faults) == 1
    assert "['transfer']" in faults[0]
    assert "no conductor will take it up" in faults[0]


def test_a_live_execution_past_the_threshold_asks_for_attention_and_states_its_age() -> None:
    keeper = _keeper(
        _execution("Running", ["tomography_scan"], 7 * 3600),
        _execution("Running", ["tomography_scan"], 3600),
    )
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter()])}, keeper, stale_hours=6))

    attention = [f["text"] for f in card["findings"] if f["level"] == "attention"]
    assert len(attention) == 1
    assert "7.0 h" in attention[0]
    assert len(card["record"]["live"]) == 2


def test_a_fleet_on_two_revisions_asks_for_attention_and_names_both() -> None:
    state = _fold(
        {
            "19-bm": _answer([_conductor(), _reporter()], revision="aaaaaaa1"),
            "7-bm": _answer([_conductor(), _reporter()], revision="bbbbbbb2"),
        }
    )

    assert state["fleet"]["level"] == "attention"
    spread = state["disagreements"][0]["text"]
    assert "aaaaaaa" in spread
    assert "bbbbbbb" in spread


def test_a_keeper_that_answers_and_is_not_ready_is_down_on_the_central_host() -> None:
    keeper = _keeper()
    keeper.ready = "503 from /readyz: schema behind"
    state = FLEET.fold(TREE, FLEET.Book(), {}, None, keeper, now=NOW)

    assert _part(state["central"], "cora-keeper")["health"] == "down"
    assert state["central"]["level"] == "fault"


def test_a_beamline_with_no_single_routable_host_and_no_conductor_key_is_not_guessed(
    tmp_path: Path,
) -> None:
    book_file = tmp_path / "hosts.toml"
    book_file.write_text(
        '[beamline."2-bm"]\nroutable = []\nprivate = ["private-a", "private-b"]\naccount = "a"\n'
        '[beamline."7-bm"]\nroutable = ["screens"]\nprivate = ["private-c"]\naccount = "b"\n'
        '[beamline."19-bm"]\nroutable = ["screens-2"]\nconductor = "private-d"\naccount = "c"\n',
        encoding="utf-8",
    )
    book = FLEET.read_book(book_file, ["2-bm", "7-bm", "19-bm"], {})

    assert "2-bm" not in book.targets
    assert "conductor" in book.missing["2-bm"]
    assert book.targets["7-bm"].ssh == "b@screens"
    assert book.targets["19-bm"].ssh == "c@private-d"


def test_a_unit_name_unsafe_to_write_into_a_script_is_not_asked_elsewhere() -> None:
    hostile = FLEET.Unit("cora-x.service; reboot", "enabled", "inactive", "ioc-host")
    pinned = FLEET.pinned_elsewhere("conductor-host", [hostile, _simulator()])

    assert pinned == {"ioc-host": ["cora-tomoscan-sim.service"]}


def test_a_snapshot_or_inventory_where_git_would_track_it_is_refused(tmp_path: Path) -> None:
    assert FLEET.snapshot_refusal(TREE_ROOT / "fleet-snapshot.html") is not None
    assert FLEET.snapshot_refusal(tmp_path / "fleet-snapshot.html") is None
    assert FLEET._refusal(TREE_ROOT / "fleet-seen.json", "the inventory") is not None


def test_a_snapshot_page_carries_its_state_and_cannot_be_closed_by_it() -> None:
    state = FLEET.fold(TREE, FLEET.Book(), {}, None, None, now=NOW)
    state["verdict"]["detail"] = "</script><b>"
    html = FLEET.page(state)

    assert '<script id="seed" type="application/json">null</script>' not in html
    assert "</script><b>" not in html


def test_a_conductor_active_under_systemd_whose_keeper_refuses_it_is_degraded() -> None:
    refused = _reach(*REFUSED)
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter()], keeper=refused)}))

    conductor = _part(card, "cora-conductor")
    assert conductor["health"] == "degraded"
    assert "refuses" in conductor["cause"]["text"]


def test_a_running_conductor_flooding_its_log_with_errors_is_degraded() -> None:
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter()], errors=120)}))

    conductor = _part(card, "cora-conductor")
    assert conductor["health"] == "degraded"
    assert "120 errors" in conductor["cause"]["text"]


def test_a_keeper_refused_from_every_conductor_host_is_down_though_unread_from_here() -> None:
    refused = _reach(*REFUSED)
    state = _fold(
        {
            "19-bm": _answer([_conductor(), _reporter()], keeper=refused),
            "7-bm": _answer([_conductor(), _reporter()], keeper=refused),
        }
    )

    assert _part(state["central"], "cora-keeper")["health"] == "down"
    assert state["verdict"]["title"] == "Keeper down"
    assert state["verdict"]["lead"].startswith("The keeper is down")
    reporter = _part(_card(state), "cora-reporter")
    assert reporter["health"] == "degraded"


def test_a_keeper_answering_one_conductor_host_is_up_though_this_page_cannot_reach_it() -> None:
    state = _fold(
        {
            "19-bm": _answer([_conductor(), _reporter()], keeper=_reach(*REFUSED)),
            "7-bm": _answer([_conductor(), _reporter()], keeper=_reach("200")),
        }
    )

    assert _part(state["central"], "cora-keeper")["health"] == "healthy"


def test_a_component_seen_before_and_unasked_now_stays_on_the_page_as_unknown() -> None:
    seen = {
        "19-bm/cora-watcher.service": {
            "owner": "19-bm",
            "name": "cora-watcher.service",
            "host": "conductor-host",
            "enabled": "enabled",
            "active": "active",
            "at": NOW - 3600,
        }
    }
    card = _card(
        _fold({"19-bm": _answer([], unreachable="Permission denied (publickey)")}, seen=seen)
    )

    watcher = _part(card, "cora-watcher")
    assert watcher["health"] == "unknown"
    assert "Last seen active" in watcher["cause"]["text"]


def test_a_unit_seen_before_and_gone_from_an_account_that_was_read_is_a_disagreement() -> None:
    seen = {
        "19-bm/cora-watcher.service": {
            "owner": "19-bm",
            "name": "cora-watcher.service",
            "host": "conductor-host",
            "active": "active",
            "at": NOW - 3600,
        }
    }
    state = _fold({"19-bm": _answer([_conductor(), _reporter()])}, seen=seen)

    assert _part(_card(state), "cora-watcher")["health"] == "notinstalled"
    assert any("cora-watcher" in item["where"] for item in state["disagreements"])


def test_a_refused_ssh_login_is_told_apart_from_a_host_that_is_not_there() -> None:
    refused = FLEET.why_unasked("acct@host: Permission denied (publickey,password).")
    missing = FLEET.why_unasked("ssh: Could not resolve hostname host: nodename nor servname")
    slow = FLEET.why_unasked("Connection timed out during banner exchange")

    assert (refused["tag"], refused["fix"]) == ("login refused", "hosts")
    assert missing["tag"] == "name does not resolve"
    assert slow["tag"] == "did not answer in time"


def test_a_unit_pinned_to_another_host_is_asked_through_the_conductor_host() -> None:
    target = FLEET.Target("conductor-host", "acct")
    listed = FLEET.commands("19-bm", target, ["ioc-host"])

    assert FLEET.hop(target) == ["-J", "acct@conductor-host"]
    assert any("ssh -J acct@conductor-host acct@ioc-host" in c["run"] for c in listed)


def test_units_pinned_to_the_central_host_are_drawn_there_not_under_their_account() -> None:
    keeper_unit = FLEET.Unit("cora-keeper.service", "enabled", "inactive", "central-host")
    elsewhere = {"cora-keeper.service": ("central-host", "inactive", "")}
    units = [_conductor(), _reporter(), keeper_unit]
    state = _fold({"19-bm": _answer(units, elsewhere, keeper=_reach(*REFUSED))})

    assert all(part["id"] != "cora-keeper" for part in _card(state)["parts"])
    keeper = _part(state["central"], "cora-keeper")
    assert keeper["health"] == "down"
    assert "central-host" in keeper["where"]


def test_a_leg_last_done_is_proven_and_one_last_broken_is_failing() -> None:
    keeper = _keeper(
        _execution("Done", ["move"], 600),
        _execution("Broken", ["process"], 600),
    )
    routines = ("tomography_scan", "move", "process")
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter()], routines=routines)}, keeper))

    assert card["legs"]["move"]["state"] == "proven"
    assert card["legs"]["process"]["state"] == "failing"


@pytest.mark.parametrize(
    ("newer", "older", "expected"),
    [
        (("Done", "process"), ("Broken", "reconstruct"), "proven"),
        (("Broken", "reconstruct"), ("Done", "process"), "failing"),
    ],
)
def test_a_lane_running_two_operations_takes_the_latest_run_of_either(
    newer: tuple[str, str], older: tuple[str, str], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lane shared by an operation and the one it replaced ranks neither above the other."""
    shared = (("process", "reconstruct"), "process", "Process")
    lanes = tuple(
        shared if lane == "process" else (ops, lane, name) for ops, lane, name in FLEET.LANES
    )
    monkeypatch.setattr(FLEET, "LANES", lanes)
    keeper = _keeper(
        _execution(newer[0], [newer[1]], 60),
        _execution(older[0], [older[1]], 600),
    )
    routines = ("tomography_scan", "move", "process", "reconstruct")
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter()], routines=routines)}, keeper))

    assert card["legs"]["process"]["state"] == expected


def test_every_declared_data_leg_is_blocked_while_the_keeper_is_down() -> None:
    refused = _reach(*REFUSED)
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter()], keeper=refused)}))

    declared = [leg for leg in card["legs"].values() if leg["state"] != "absent"]
    assert declared
    assert all(leg["state"] == "blocked" for leg in declared)


def test_a_deployed_revision_behind_the_tree_is_drifted_with_its_distance() -> None:
    state = _fold(
        {"19-bm": _answer([_conductor(), _reporter()], revision="1234567")},
        distance={"1234567": 57},
    )

    conductor = _part(_card(state), "cora-conductor")
    assert conductor["sync"] == "drifted"
    assert "57 commits behind" in conductor["sync_why"]
    assert _card(state)["version"] == {"state": "drifted", "revision": "1234567", "behind": 57}


def _templates() -> dict[str, Path]:
    """Every unit template git tracks, by kind, as a path from the tree's root."""
    listed = subprocess.run(
        ["git", "ls-files", "*.service.in"],
        cwd=TREE_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    paths = [Path(line) for line in listed.stdout.split()]
    return {path.name.removesuffix(".service.in"): path for path in paths}


def test_every_kind_the_page_names_is_a_unit_template_the_tree_ships() -> None:
    shipped = set(_templates())

    assert len(shipped) >= MINIMUM_TEMPLATES
    assert set(FLEET.KINDS) == shipped
    assert set(FLEET.DESCRIPTIONS) == shipped
    assert set(FLEET.EVERY_BEAMLINE) | set(FLEET.ON_THE_CENTRAL_HOST) <= shipped


def test_every_unit_belongs_to_the_package_its_template_ships_from() -> None:
    templates = _templates()
    shipped_from = {
        kind: path.parts[1] if path.parts[0] == "apps" else path.parts[0]
        for kind, path in templates.items()
    }
    apps = {path.parts[1] for path in templates.values() if path.parts[0] == "apps"}

    def tiered(wanted: str) -> set[str]:
        return {kind for kind, (_, tier) in FLEET.PACKAGES.items() if tier == wanted}

    assert {kind: package for kind, (package, _) in FLEET.PACKAGES.items()} == shipped_from
    assert tiered("main") == {f"cora-{app}" for app in apps}
    assert tiered("testing") == {kind for kind, path in templates.items() if "sim" in path.parts}
    assert tiered("main") | tiered("helper") | tiered("testing") == set(templates)


def test_every_operation_the_register_declares_runs_in_exactly_one_lane() -> None:
    lanes = [operation for operations, _, _ in FLEET.LANES for operation in operations]

    assert sorted(lanes) == sorted(TREE["operations"])


def test_a_port_already_taken_is_reported_plainly_and_nothing_is_asked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second copy of the page used to crash with a traceback after asking every host.

    Its threads started before it tried the port, so a copy that could not
    serve still sent a round of ssh logins on its way out.
    """
    started: list[str] = []

    def record(thread: threading.Thread) -> None:
        started.append(thread.name)

    monkeypatch.setattr(FLEET.threading.Thread, "start", record)
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        port = str(taken.getsockname()[1])
        code = FLEET.main(
            [
                "--host",
                "19-bm=acct@conductor-host",
                "--book",
                str(tmp_path / "absent.toml"),
                "--seen",
                str(tmp_path / "seen.json"),
                "--port",
                port,
            ]
        )

    assert code == 2
    assert "already in use" in capsys.readouterr().err
    assert started == []


def test_a_host_reached_through_the_conductor_host_shows_its_uptime_and_its_services() -> None:
    serving = {"cora-tomoscan-sim.service": ("ioc-host", "active", "")}
    pinned = {"ioc-host": {"reached": True, "uptime": 259200, "said": ""}}
    answer = _answer([_conductor(), _reporter(), _simulator()], serving, pinned=pinned)
    hosts = _card(_fold({"19-bm": answer}))["hosts"]

    assert [host["role"] for host in hosts] == ["conductor host", "beamline host"]
    assert (hosts[0]["reached"], hosts[0]["uptime"]) == (True, 3600)
    assert (hosts[1]["reached"], hosts[1]["uptime"]) == (True, 259200)
    assert "cora-tomoscan-sim" in hosts[1]["parts"]


def test_a_host_the_conductor_host_could_not_reach_reads_unreached_and_says_why() -> None:
    silent = {"cora-tomoscan-sim.service": ("ioc-host", "unasked", "Connection timed out")}
    pinned = {"ioc-host": {"reached": False, "uptime": None, "said": "Connection timed out"}}
    answer = _answer([_conductor(), _reporter(), _simulator()], silent, pinned=pinned)
    host = _card(_fold({"19-bm": answer}))["hosts"][1]

    assert host["reached"] is False
    assert host["why"] == "did not answer in time"


def test_an_engine_pointed_at_its_simulator_reads_simulated_and_otherwise_station() -> None:
    on_simulator = _answer([_conductor(), _reporter()], simulated="corasim19bm:TomoScan:")
    on_station = _answer([_conductor(), _reporter()], simulated="corasim19bm:Other:")

    assert _card(_fold({"19-bm": on_simulator}))["engine"]["kind"] == "simulated"
    assert _card(_fold({"19-bm": on_station}))["engine"]["kind"] == "station"


def test_the_keeper_link_reads_refused_from_a_conductor_host_the_keeper_refuses() -> None:
    refused = _answer([_conductor(), _reporter()], keeper=_reach(*REFUSED))
    answering = _answer([_conductor(), _reporter()])

    assert _card(_fold({"19-bm": refused}))["keeper_link"]["state"] == "refused"
    assert _card(_fold({"19-bm": answering}))["keeper_link"]["state"] == "ok"


def test_the_central_host_reads_up_from_a_hop_that_reached_it() -> None:
    keeper_unit = FLEET.Unit("cora-keeper.service", "enabled", "active", "central-host")
    elsewhere = {"cora-keeper.service": ("central-host", "active", "")}
    pinned = {"central-host": {"reached": True, "uptime": 1_000_000, "said": ""}}
    answer = _answer([_conductor(), _reporter(), keeper_unit], elsewhere, pinned=pinned)
    host = _fold({"19-bm": answer})["central"]["hosts"][0]

    assert (host["role"], host["reached"], host["uptime"]) == ("central host", True, 1_000_000)


def test_a_keeper_seen_only_from_conductor_hosts_is_a_partial_source_not_a_failure() -> None:
    state = _fold({"19-bm": _answer([_conductor(), _reporter()])})
    keeper = next(source for source in state["sources"] if source["id"] == "keeper")

    assert keeper["state"] == "partial"
    assert "1 of 1 conductor hosts" in keeper["why"]


def test_each_computer_carries_the_network_the_address_book_puts_it_on() -> None:
    target = FLEET.Target("conductor-host", "acct", ("conductor-host",), ("ioc-host",))
    book = FLEET.Book(targets={"19-bm": target}, central_host="central-host")
    serving = {"cora-tomoscan-sim.service": ("ioc-host", "active", "")}
    pinned = {"ioc-host": {"reached": True, "uptime": 60, "said": ""}}
    answer = _answer([_conductor(), _reporter(), _simulator()], serving, pinned=pinned)
    state = FLEET.fold(TREE, book, {"19-bm": answer}, None, None, now=NOW)

    assert [host["network"] for host in _card(state)["hosts"]] == ["routable", "private"]


def test_a_card_marks_only_its_simulator_for_testing_and_its_packages_as_main() -> None:
    serving = {"cora-tomoscan-sim.service": ("ioc-host", "active", "")}
    card = _card(_fold({"19-bm": _answer([_conductor(), _reporter(), _simulator()], serving)}))
    tiers = {part["id"]: part["tier"] for part in card["parts"]}
    testing = [kind for kind, tier in sorted(tiers.items()) if tier == "testing"]

    assert testing == ["cora-tomoscan-sim"]
    assert (tiers["cora-conductor"], tiers["cora-reporter"]) == ("main", "main")
