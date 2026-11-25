"""The after-boot job starts what a boot missed, and nothing a person chose.

`infra/deploy/after-boot.sh` is what brings the keeper back when its host
reboots and the user manager comes up before the home that holds the units.
It runs from cron, on the host, where nothing in this suite can follow it, so
these run the script itself under bash with every command it reaches for
replaced: `systemctl` by a small model of a user manager, and `crontab`,
`logger`, `flock` and `hostname` by stand-ins that record what they were
asked.

The model knows one thing a real manager does that matters here: a unit
whose file the manager never read is not found, and starting it fails, until
the manager is told to reload. That is the state a boot without the home
leaves, and the reason the job exists. A version of the script that skipped
the reload would start nothing and fail the first test below.

## What the cases are

The job has one thing to do and several things it must not, and the second
list is longer because each item there is something a person decided:
stopping a unit, disabling it, pinning it to another host. A job that
restarted any of those would be fighting whoever runs the facility, every
five minutes, from a crontab line most of them have never read.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

pytestmark = pytest.mark.architecture

SCRIPT = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "after-boot.sh"

HOST = "this-host"
"""What the stand-in `hostname` answers, and what the units are pinned to."""

UNITS = ("keeper-postgres.service", "keeper-jwks.service", "keeper-api.service")
"""Stand-ins for the three the keeper's installer arms, in the order it names them.

Not the deployed names. Those carry a prefix that is the deploying tree's
convention rather than this project's, and the script reads names from its
command line without caring what they are.
"""

NAME = "keeper-after-boot"

_SYSTEMCTL = """
import json, os, sys

state_path = os.path.join(os.environ["STUB_STATE"], "state.json")
with open(state_path) as handle:
    state = json.load(handle)
args = sys.argv[1:]
state["calls"].append(args)

def save():
    with open(state_path, "w") as handle:
        json.dump(state, handle)

def unit(name):
    return state["units"].setdefault(name, {"load": "not-found", "active": "inactive", "since": 0})

if "--user" not in args:
    save()
    wanted = args[-1]
    sys.exit(0 if args[0] == "is-active" and wanted in state["system_active"] else 3)

args = [a for a in args if a != "--user"]
verb = args[0]
if verb == "show-environment":
    save()
    sys.exit(0 if state["manager"] else 1)
if verb == "show":
    prop = args[args.index("-p") + 1]
    record = unit(args[-1])
    save()
    print({"LoadState": record["load"], "ActiveState": record["active"],
           "InactiveExitTimestampMonotonic": record["since"]}[prop])
    sys.exit(0)
if verb == "daemon-reload":
    directory = os.path.join(os.environ["HOME"], ".config", "systemd", "user")
    for name, record in state["units"].items():
        record["load"] = "loaded" if os.path.isfile(os.path.join(directory, name)) else "not-found"
    save()
    sys.exit(0)
if verb == "start":
    record = unit(args[1])
    if record["load"] != "loaded":
        save()
        print(f"Failed to start {args[1]}: Unit {args[1]} not found.", file=sys.stderr)
        sys.exit(5)
    record["active"], record["since"] = "active", 1
    save()
    sys.exit(0)
save()
sys.exit(0)
"""

_CRONTAB = """
import os, sys

state = os.environ["STUB_STATE"]
table = os.path.join(state, "crontab")
if os.path.exists(os.path.join(state, "cron-denied")):
    print("You (someone) are not allowed to use this program (crontab)", file=sys.stderr)
    sys.exit(1)
if sys.argv[1:] == ["-l"]:
    if not os.path.exists(table):
        print("no crontab for someone", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(open(table).read())
    sys.exit(0)
if sys.argv[1:] == ["-"]:
    open(table, "w").write(sys.stdin.read())
    sys.exit(0)
sys.exit(2)
"""

_LOGGER = """
import os, sys

with open(os.path.join(os.environ["STUB_STATE"], "journal"), "a") as journal:
    tag = sys.argv[sys.argv.index("-t") + 1]
    for line in sys.stdin:
        journal.write(f"{tag}: {line}")
"""


class Host:
    """A home, a unit directory, a manager and a crontab, all stand-ins."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.units = self.home / ".config" / "systemd" / "user"
        self.wants = self.units / "default.target.wants"
        self.state = root / "state"
        self.bin = root / "bin"
        self.runtime = root / "runtime"
        for directory in (self.wants, self.state, self.bin, self.runtime):
            directory.mkdir(parents=True)
        self._write({"manager": True, "system_active": ["crond.service"], "units": {}, "calls": []})
        self._stub("systemctl", _SYSTEMCTL)
        self._stub("crontab", _CRONTAB)
        self._stub("logger", _LOGGER)
        self._shell("flock", "exit 0")
        self._shell("hostname", f"echo {HOST}")

    def _stub(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)

    def _shell(self, name: str, body: str) -> None:
        path = self.bin / name
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        path.chmod(0o755)

    def _read(self) -> dict[str, object]:
        return json.loads((self.state / "state.json").read_text(encoding="utf-8"))

    def _write(self, state: dict[str, object]) -> None:
        (self.state / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def install(self, unit: str, *, pinned: str | None = HOST, enabled: bool = True) -> None:
        """A unit file in the shared home, the way an installer leaves one."""
        condition = f"ConditionHost={pinned}\n" if pinned is not None else ""
        (self.units / unit).write_text(
            f"[Unit]\nDescription=stand-in\n{condition}\n[Install]\nWantedBy=default.target\n",
            encoding="utf-8",
        )
        if enabled:
            (self.wants / unit).symlink_to(self.units / unit)

    def manager_sees(
        self, unit: str, *, load: str, active: str = "inactive", since: int = 0
    ) -> None:
        """What the user manager believes about one unit."""
        state = self._read()
        units = state["units"]
        assert isinstance(units, dict)
        units[unit] = {"load": load, "active": active, "since": since}
        self._write(state)

    def no_manager(self) -> None:
        state = self._read()
        state["manager"] = False
        self._write(state)

    def guard(self, name: str, *, passes: bool, says: str) -> Path:
        path = self.root / name
        path.write_text(f"#!/bin/sh\necho '{says}'\nexit {0 if passes else 1}\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    def run(self, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(self.home),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "STUB_STATE": str(self.state),
            "XDG_RUNTIME_DIR": str(self.runtime),
        }
        done = subprocess.run(
            ["bash", str(SCRIPT), *arguments],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if check:
            assert done.returncode == 0, done.stderr
        return done

    def calls(self) -> list[list[str]]:
        calls = cast("list[list[str]]", self._read()["calls"])
        return [[word for word in call if word != "--user"] for call in calls]

    def started(self) -> list[str]:
        return [call[1] for call in self.calls() if call[0] == "start"]

    def reloaded(self) -> bool:
        return ["daemon-reload"] in self.calls()

    def journal(self) -> str:
        path = self.state / "journal"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def crontab(self) -> str:
        return (self.state / "crontab").read_text(encoding="utf-8")


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def _armed(host: Host, *specs: str) -> list[str]:
    host.run("run", NAME, *specs)
    return host.started()


def test_a_boot_that_never_read_the_units_is_reloaded_and_each_unit_started(host: Host) -> None:
    for unit in UNITS:
        host.install(unit)
        host.manager_sees(unit, load="not-found")

    started = _armed(host, *UNITS)

    assert host.reloaded(), "the manager was never told to read its unit directory again"
    assert started == list(UNITS)
    reload_at = host.calls().index(["daemon-reload"])
    first_start = next(i for i, call in enumerate(host.calls()) if call[0] == "start")
    assert reload_at < first_start, "a start before the reload finds no unit to start"
    assert "had not read" in host.journal()


def test_a_boot_that_started_everything_leaves_the_job_with_nothing_to_do(host: Host) -> None:
    for unit in UNITS:
        host.install(unit)
        host.manager_sees(unit, load="loaded", active="active", since=42)

    started = _armed(host, *UNITS)

    assert started == []
    assert not host.reloaded()
    assert host.journal() == "", "a tick with nothing to do wrote to the journal"


def test_a_unit_stopped_by_a_person_after_it_ran_is_not_started_again(host: Host) -> None:
    for unit in UNITS:
        host.install(unit)
        host.manager_sees(unit, load="loaded", active="active", since=42)
    host.manager_sees("keeper-api.service", load="loaded", active="inactive", since=42)

    assert _armed(host, *UNITS) == []


def test_a_loaded_unit_that_this_boot_never_tried_is_started_without_a_reload(host: Host) -> None:
    host.install("keeper-api.service")
    host.manager_sees("keeper-api.service", load="loaded", active="inactive", since=0)

    assert _armed(host, "keeper-api.service") == ["keeper-api.service"]
    assert not host.reloaded()


def test_a_disabled_unit_is_neither_reloaded_for_nor_started(host: Host) -> None:
    host.install("keeper-api.service", enabled=False)
    host.manager_sees("keeper-api.service", load="not-found")

    assert _armed(host, "keeper-api.service") == []
    assert not host.reloaded()


def test_a_unit_pinned_to_another_host_is_neither_reloaded_for_nor_started(host: Host) -> None:
    host.install("keeper-api.service", pinned="another-host")
    host.manager_sees("keeper-api.service", load="not-found")

    assert _armed(host, "keeper-api.service") == []
    assert not host.reloaded()


def test_a_unit_pinned_to_no_host_is_not_claimed_by_this_one(host: Host) -> None:
    host.install("keeper-api.service", pinned=None)
    host.manager_sees("keeper-api.service", load="not-found")

    assert _armed(host, "keeper-api.service") == []


def test_a_unit_whose_file_is_absent_is_not_started(host: Host) -> None:
    host.manager_sees("keeper-api.service", load="not-found")

    assert _armed(host, "keeper-api.service") == []
    assert not host.reloaded()


def test_no_user_manager_yet_means_the_job_asks_nothing_further_and_says_nothing(
    host: Host,
) -> None:
    for unit in UNITS:
        host.install(unit)
        host.manager_sees(unit, load="not-found")
    host.no_manager()

    assert _armed(host, *UNITS) == []
    assert host.calls() == [["show-environment"]]
    assert host.journal() == ""


def test_a_guard_that_refuses_holds_its_unit_and_lets_the_others_start(host: Host) -> None:
    for unit in UNITS:
        host.install(unit)
        host.manager_sees(unit, load="not-found")
    guard = host.guard("queue", passes=False, says="two executions are waiting at 7-bm")

    started = _armed(host, *UNITS[:2], f"keeper-api.service={guard}")

    assert started == list(UNITS[:2])
    assert "two executions are waiting at 7-bm" in host.journal()
    assert "holding keeper-api.service" in host.journal()


def test_a_guard_that_allows_lets_its_unit_start(host: Host) -> None:
    host.install("keeper-api.service")
    host.manager_sees("keeper-api.service", load="not-found")
    guard = host.guard("queue", passes=True, says="nothing is waiting")

    assert _armed(host, f"keeper-api.service={guard}") == ["keeper-api.service"]


def test_the_journal_lines_carry_the_name_the_job_was_armed_under(host: Host) -> None:
    host.install("keeper-api.service")
    host.manager_sees("keeper-api.service", load="not-found")

    _armed(host, "keeper-api.service")

    lines = host.journal().splitlines()
    assert lines
    assert all(line.startswith(f"{NAME}: ") for line in lines)


def test_arming_into_an_empty_crontab_writes_one_line_that_runs_this_script(host: Host) -> None:
    host.run("arm", NAME, *UNITS)

    lines = host.crontab().splitlines()
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith("*/5 * * * * /bin/bash ")
    assert f"{SCRIPT} run {NAME} {' '.join(UNITS)}" in line
    assert line.endswith(f" # {NAME}")


def test_arming_keeps_every_line_somebody_else_wrote(host: Host) -> None:
    theirs = "MAILTO=staff\n0 3 * * * /usr/bin/true nightly\n\n15 * * * * /usr/bin/true hourly\n"
    (host.state / "crontab").write_text(theirs, encoding="utf-8")

    host.run("arm", NAME, *UNITS)

    assert host.crontab().startswith(theirs)
    assert host.crontab().count(f"# {NAME}") == 1


def test_arming_twice_replaces_the_line_rather_than_adding_a_second(host: Host) -> None:
    host.run("arm", NAME, *UNITS)
    host.run("arm", NAME, "keeper-api.service")

    lines = host.crontab().splitlines()
    assert len(lines) == 1
    assert lines[0].endswith(f"run {NAME} keeper-api.service # {NAME}")


def test_arming_leaves_another_apps_line_alone(host: Host) -> None:
    host.run("arm", "thinker-after-boot", "thinker.service")
    host.run("arm", NAME, *UNITS)

    assert host.crontab().count("# thinker-after-boot") == 1
    assert host.crontab().count(f"# {NAME}") == 1


def test_arming_where_cron_is_denied_refuses_and_writes_nothing(host: Host) -> None:
    (host.state / "cron-denied").touch()

    done = host.run("arm", NAME, *UNITS, check=False)

    assert done.returncode != 0
    assert "refused" in done.stderr
    assert not (host.state / "crontab").exists()


def test_arming_a_unit_a_shell_would_split_is_refused(host: Host) -> None:
    done = host.run("arm", NAME, "keeper-api.service; rm -rf ~", check=False)

    assert done.returncode != 0
    assert not (host.state / "crontab").exists()


def test_arming_a_guard_that_is_not_executable_is_refused(host: Host) -> None:
    done = host.run("arm", NAME, f"keeper-api.service={host.root}/absent", check=False)

    assert done.returncode != 0
    assert not (host.state / "crontab").exists()


def test_the_check_passes_where_cron_runs_and_the_account_may_use_it(host: Host) -> None:
    assert host.run("check", check=False).returncode == 0


def test_the_check_refuses_where_cron_is_not_running(host: Host) -> None:
    state = json.loads((host.state / "state.json").read_text(encoding="utf-8"))
    state["system_active"] = []
    (host.state / "state.json").write_text(json.dumps(state), encoding="utf-8")

    done = host.run("check", check=False)

    assert done.returncode != 0
    assert "cron is not running" in done.stderr


def test_the_check_refuses_where_the_account_may_not_use_cron(host: Host) -> None:
    (host.state / "cron-denied").touch()

    done = host.run("check", check=False)

    assert done.returncode != 0
    assert "cannot use cron" in done.stderr
