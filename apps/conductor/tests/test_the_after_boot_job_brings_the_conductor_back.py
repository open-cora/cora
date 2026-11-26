"""After its host reboots, a conductor comes back only when nothing is waiting for it.

Enabled, pinned and lingering is not enough where the home is NFS. A
lingering user manager can start before the home is mounted, find no unit
there, and never look again, which left every service on the central host
down for two weeks once. `infra/deploy/after-boot.sh` is the repair, armed
by the installer as a crontab line on the host it installs on.

The script is byte-identical to the copy the other apps carry, and the
development tree proves the copies agree. This suite still runs its own
copy, because a mirror has to stand alone, and because a conductor is the
unit here whose return is guarded: what the guard is handed and what its
answer does are this project's to pin.

Every command the script reaches for is replaced. `systemctl` is a small
model of a user manager that refuses to start a unit it never read until it
is told to reload, which is the behavior the job is written against.

## The installer's half

Arming is a block of its own in `infra/deploy/install.sh`, and it decides
three things nobody sees go wrong until a reboot: which units the line
names, that each one names the guard, and that a guard unable to read the
queue stops the deploy. So the block is run here as it is written, under
bash, with the two scripts it calls replaced by stand-ins that record what
they were asked. The unit names it is handed are read from the installer's
own spelling of them, so renaming the unit in one place and not the other
fails here.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "infra" / "deploy"
SCRIPT = DEPLOY / "after-boot.sh"
INSTALLER = DEPLOY / "install.sh"
GUARD = DEPLOY / "nothing-is-waiting.sh"

HOST = "this-host"
"""What the stand-in `hostname` answers, and what the units are pinned to."""

NAME = "conductor-after-boot"
UNIT = "conductor.service"
SECOND = "conductor-transfer.service"
"""Stand-ins for the job and two conductors on one host.

Not the deployed names, which carry the deploying tree's prefix. The script
reads names from its command line without caring what they are; the block
tests below read the deployed names from the installer instead.
"""

_SYSTEMCTL = """
import json, os, sys

state_path = os.path.join(os.environ["STUB_STATE"], "state.json")
with open(state_path) as handle:
    state = json.load(handle)
args = sys.argv[1:]

def save():
    with open(state_path, "w") as handle:
        json.dump(state, handle)

if "--user" not in args:
    save()
    sys.exit(0 if args[0] == "is-active" and args[-1] in state["system_active"] else 3)

args = [a for a in args if a != "--user"]
state["calls"].append(args)
verb = args[0]
if verb == "show-environment":
    save()
    sys.exit(0)
if verb == "show":
    prop = args[args.index("-p") + 1]
    record = state["units"][args[-1]]
    save()
    print({"LoadState": record["load"], "ActiveState": record["active"],
           "InactiveExitTimestampMonotonic": record["since"]}[prop])
    sys.exit(0)
if verb == "daemon-reload":
    for record in state["units"].values():
        record["load"] = "loaded"
    save()
    sys.exit(0)
if verb == "start":
    record = state["units"][args[1]]
    if record["load"] != "loaded":
        save()
        sys.exit(5)
    record["active"], record["since"] = "active", 1
    save()
    sys.exit(0)
save()
sys.exit(0)
"""

_CRONTAB = """
import os, sys

table = os.path.join(os.environ["STUB_STATE"], "crontab")
if sys.argv[1:] == ["-l"]:
    if not os.path.exists(table):
        print("no crontab for someone", file=sys.stderr)
        sys.exit(1)
    sys.stdout.write(open(table).read())
elif sys.argv[1:] == ["-"]:
    open(table, "w").write(sys.stdin.read())
"""

_LOGGER = """
import os, sys

with open(os.path.join(os.environ["STUB_STATE"], "journal"), "a") as journal:
    journal.write(sys.stdin.read())
"""


def _executable(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)
    return path


class Host:
    """A shared home holding conductor units, a manager's view of them, and a guard."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.units = self.home / ".config" / "systemd" / "user"
        (self.units / "default.target.wants").mkdir(parents=True)
        self.state = root / "state"
        self.state.mkdir()
        self._write({"system_active": ["crond.service"], "units": {}, "calls": []})
        stubs = root / "bin"
        stubs.mkdir()
        for name, body in (("systemctl", _SYSTEMCTL), ("crontab", _CRONTAB), ("logger", _LOGGER)):
            _executable(stubs / name, f"#!{sys.executable}\n{body}")
        _executable(stubs / "flock", "#!/bin/sh\nexit 0\n")
        _executable(stubs / "hostname", f"#!/bin/sh\necho {HOST}\n")
        (root / "runtime").mkdir()
        self.env = {
            "HOME": str(self.home),
            "PATH": f"{stubs}:{os.environ['PATH']}",
            "STUB_STATE": str(self.state),
            "XDG_RUNTIME_DIR": str(root / "runtime"),
        }

    def _read(self) -> dict[str, object]:
        return json.loads((self.state / "state.json").read_text(encoding="utf-8"))

    def _write(self, state: dict[str, object]) -> None:
        (self.state / "state.json").write_text(json.dumps(state), encoding="utf-8")

    def install(self, unit: str, *, load: str, active: str = "inactive", since: int = 0) -> None:
        """A conductor in the shared home, enabled and pinned here, as the manager sees it."""
        (self.units / unit).write_text(
            f"[Unit]\nConditionHost={HOST}\n[Install]\nWantedBy=default.target\n",
            encoding="utf-8",
        )
        (self.units / "default.target.wants" / unit).symlink_to(self.units / unit)
        state = self._read()
        units = cast("dict[str, object]", state["units"])
        units[unit] = {"load": load, "active": active, "since": since}
        self._write(state)

    def guard(self, *, holds: str | None) -> Path:
        """A guard that records which unit it was asked about, and holds the one named."""
        asked = self.root / "asked"
        refusal = f'[ "$1" = "{holds}" ] && {{ echo "work is waiting for $1"; exit 1; }}'
        return _executable(
            self.root / "guard",
            f'#!/bin/sh\necho "$1" >> "{asked}"\n{refusal if holds else ""}\nexit 0\n',
        )

    def asked(self) -> list[str]:
        path = self.root / "asked"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def run(self, *arguments: str) -> None:
        done = subprocess.run(
            ["bash", str(SCRIPT), *arguments],
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr

    def calls(self) -> list[list[str]]:
        return cast("list[list[str]]", self._read()["calls"])

    def started(self) -> list[str]:
        return [call[1] for call in self.calls() if call[0] == "start"]

    def journal(self) -> str:
        path = self.state / "journal"
        return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.fixture
def host(tmp_path: Path) -> Host:
    return Host(tmp_path)


def test_a_boot_that_never_read_the_conductor_reloads_asks_its_guard_and_starts_it(
    host: Host,
) -> None:
    host.install(UNIT, load="not-found")
    guard = host.guard(holds=None)

    host.run("run", NAME, f"{UNIT}={guard}")

    calls = host.calls()
    assert ["daemon-reload"] in calls
    assert host.started() == [UNIT]
    assert calls.index(["daemon-reload"]) < calls.index(["start", UNIT])
    assert host.asked() == [UNIT], "the guard was not told which conductor it was asked about"


def test_a_guard_that_finds_work_waiting_holds_the_conductor_and_the_journal_says_why(
    host: Host,
) -> None:
    host.install(UNIT, load="not-found")
    guard = host.guard(holds=UNIT)

    host.run("run", NAME, f"{UNIT}={guard}")

    assert host.started() == []
    assert f"work is waiting for {UNIT}" in host.journal()
    assert f"holding {UNIT}" in host.journal()


def test_each_conductor_on_one_line_is_asked_about_by_its_own_name(host: Host) -> None:
    host.install(UNIT, load="not-found")
    host.install(SECOND, load="not-found")
    guard = host.guard(holds=SECOND)

    host.run("run", NAME, f"{UNIT}={guard}", f"{SECOND}={guard}")

    assert sorted(host.asked()) == sorted([UNIT, SECOND])
    assert host.started() == [UNIT], (
        "one guard stands beside both conductors, and only the one with work waiting should be held"
    )


def test_a_conductor_somebody_stopped_is_left_stopped_and_its_guard_is_not_asked(
    host: Host,
) -> None:
    host.install(UNIT, load="loaded", active="inactive", since=42)
    guard = host.guard(holds=None)

    host.run("run", NAME, f"{UNIT}={guard}")

    assert host.started() == []
    assert host.asked() == []
    assert host.journal() == ""


def test_arming_twice_leaves_one_line_naming_each_conductor_and_its_guard(host: Host) -> None:
    guard = host.guard(holds=None)

    host.run("arm", NAME, f"{UNIT}={guard}", f"{SECOND}={guard}")
    host.run("arm", NAME, f"{UNIT}={guard}", f"{SECOND}={guard}")

    lines = (host.state / "crontab").read_text(encoding="utf-8").splitlines()
    assert lines == [
        f"*/5 * * * * /bin/bash {SCRIPT} run {NAME} {UNIT}={guard} {SECOND}={guard} # {NAME}"
    ]


_UNIT_SPELLINGS = re.compile(r'UNIT="([^"]+\.service)"')
"""The installer's two spellings of its unit's name, plain and per instance."""

_BLOCK = ('echo "After a reboot"', 'echo "Done.')
"""Where the arming block starts in the installer, and what follows it."""


def _deployed_names() -> tuple[str, str]:
    spelled = _UNIT_SPELLINGS.findall(INSTALLER.read_text(encoding="utf-8"))
    assert len(spelled) == 2, f"the installer spells its unit {spelled}, not plain and per instance"
    plain, per_instance = spelled
    assert "${INSTANCE}" in per_instance
    return plain, per_instance


def _arming_block() -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    start = text.find(_BLOCK[0])
    end = text.find(_BLOCK[1], start)
    assert start != -1, f"install.sh has no {_BLOCK[0]!r}, so there is no arming block to run"
    assert end != -1, f"nothing follows the arming block; expected {_BLOCK[1]!r}"
    return text[start:end]


@dataclass(frozen=True)
class Arming:
    """What the installer's arming block did, read from its two stand-ins."""

    done: subprocess.CompletedProcess[str]
    armed: list[str] | None
    asked: list[str] | None


def _arm(tmp_path: Path, *, installed: str, pinned: dict[str, str], guard_exits: int) -> Arming:
    """Run the arming block with `installed` just written and `pinned` already in the home."""
    deploy, units, record = tmp_path / "deploy", tmp_path / "units", tmp_path / "record"
    for directory in (deploy, units, record):
        directory.mkdir()
    for unit, where in pinned.items():
        (units / unit).write_text(f"[Unit]\nConditionHost={where}\n", encoding="utf-8")
    _executable(
        deploy / SCRIPT.name,
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}/armed"\necho "a crontab line"\n',
    )
    _executable(
        deploy / GUARD.name,
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "{record}/asked"\n'
        f'echo "what the guard found"\nexit {guard_exits}\n',
    )
    prelude = "\n".join(
        (
            "set -euo pipefail",
            "say() { printf '  %s\\n' \"$*\"; }",
            "die() { printf 'error: %s\\n' \"$*\" >&2; exit 1; }",
            f"SCRIPT_DIR={shlex.quote(str(deploy))}",
            f"UNIT_DIR={shlex.quote(str(units))}",
            f"UNIT={shlex.quote(installed)}",
            f"DEPLOY_HOST={HOST}",
            "",
        )
    )
    block = tmp_path / "arming.sh"
    block.write_text(prelude + _arming_block(), encoding="utf-8")
    done = subprocess.run(
        ["bash", str(block)],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )

    def lines(name: str) -> list[str] | None:
        path = record / name
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else None

    return Arming(done=done, armed=lines("armed"), asked=lines("asked"))


def test_the_installer_arms_every_conductor_pinned_here_and_nothing_else(tmp_path: Path) -> None:
    plain, per_instance = _deployed_names()
    transfer = per_instance.replace("${INSTANCE}", "transfer")
    elsewhere = per_instance.replace("${INSTANCE}", "scan")
    guard = str(tmp_path / "deploy" / GUARD.name)

    arming = _arm(
        tmp_path,
        installed=plain,
        pinned={plain: HOST, transfer: HOST, elsewhere: "another-host", "other.service": HOST},
        guard_exits=0,
    )

    assert arming.done.returncode == 0, arming.done.stderr
    assert arming.armed is not None, "the block never armed the job"
    verb, name, *units = arming.armed
    assert verb == "arm"
    assert name == plain.removesuffix(".service") + "-after-boot", (
        f"the job is armed as {name}, and the name has to be the unit's own "
        "followed by -after-boot: it marks the crontab line the next deploy "
        "replaces, and a name shared with another app replaces that app's line"
    )
    assert sorted(units) == sorted([f"{plain}={guard}", f"{transfer}={guard}"]), (
        f"armed {units}. Every conductor pinned to this host belongs on the line "
        "with the guard beside it, and nothing pinned elsewhere or belonging to "
        "another app does"
    )


def test_the_installer_asks_the_guard_about_the_conductor_it_just_installed(
    tmp_path: Path,
) -> None:
    plain, per_instance = _deployed_names()
    transfer = per_instance.replace("${INSTANCE}", "transfer")

    arming = _arm(tmp_path, installed=transfer, pinned={plain: HOST, transfer: HOST}, guard_exits=0)

    assert arming.asked == [transfer]


def test_the_installer_refuses_and_arms_nothing_when_the_guard_cannot_read_the_queue(
    tmp_path: Path,
) -> None:
    plain, _ = _deployed_names()

    arming = _arm(tmp_path, installed=plain, pinned={plain: HOST}, guard_exits=2)

    assert arming.done.returncode != 0, (
        "a guard that cannot read the queue holds the conductor after every boot "
        "the job acts on, so the deploy that would arm it has to fail"
    )
    assert arming.armed is None
    assert "cannot read the queue" in arming.done.stderr


def test_work_waiting_at_install_time_is_reported_and_the_job_is_still_armed(
    tmp_path: Path,
) -> None:
    plain, _ = _deployed_names()

    arming = _arm(tmp_path, installed=plain, pinned={plain: HOST}, guard_exits=1)

    assert arming.done.returncode == 0, arming.done.stderr
    assert arming.armed is not None
    assert "what the guard found" in arming.done.stdout
    assert "would hold" in arming.done.stdout


def test_the_installer_asks_whether_cron_can_run_the_job_before_it_changes_anything() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    check = text.find('after-boot.sh" check')
    changes = {
        "write a revision": text.find('> "${APP_DIR}/REVISION"'),
        "build the virtualenv": text.find("uv sync"),
        "make the unit directory": text.find('mkdir -p "${UNIT_DIR}"'),
    }

    assert check != -1, "install.sh never asks whether this host can run the job"
    assert all(offset != -1 for offset in changes.values()), changes
    assert all(check < offset for offset in changes.values()), (
        "install.sh asks whether cron can run the job only after it has started "
        "changing the host, so a refusal leaves half a deployment behind"
    )


def test_the_guard_the_installer_names_ships_beside_it_and_is_executable() -> None:
    assert f"${{SCRIPT_DIR}}/{GUARD.name}" in INSTALLER.read_text(encoding="utf-8")
    assert GUARD.is_file()
    assert GUARD.stat().st_mode & 0o111, (
        "the guard is not executable, so arming refuses it, and a host that got "
        "one anyway would hold the conductor after every boot the job acts on"
    )
