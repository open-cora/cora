"""After its host reboots, the thinker comes back without anybody starting it.

Enabled, pinned and lingering is not enough where the home is NFS. A
lingering user manager can start before the home is mounted, find no unit
there, and never look again, and that left every service on the central host
down for two weeks once, this one included. `infra/deploy/after-boot.sh` is
the repair, armed by the installer as a crontab line on the host it installs
on.

The script is byte-identical to the copy the other apps carry, and the
development tree proves the copies agree. This suite still runs its own
copy, because a mirror has to stand alone: the cases are the one the job
exists for, a boot that never read the unit, and the one it must never get
wrong, a unit somebody stopped.

Every command the script reaches for is replaced. `systemctl` is a small
model of a user manager that refuses to start a unit it never read until it
is told to reload, which is the behavior the job is written against.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "infra" / "deploy"
SCRIPT = DEPLOY / "after-boot.sh"
INSTALLER = DEPLOY / "install.sh"

UNIT = "cora-thinker.service"
NAME = "cora-thinker-after-boot"
HOST = "this-host"

_SYSTEMCTL = """
import json, os, sys

state_path = os.path.join(os.environ["STUB_STATE"], "state.json")
state = json.load(open(state_path))
args = [a for a in sys.argv[1:] if a != "--user"]
state["calls"].append(args)
record = state["unit"]
verb = args[0]
code = 0
if verb == "show-environment":
    pass
elif verb == "show":
    prop = args[args.index("-p") + 1]
    print({"LoadState": record["load"], "ActiveState": record["active"],
           "InactiveExitTimestampMonotonic": record["since"]}[prop])
elif verb == "daemon-reload":
    record["load"] = "loaded"
elif verb == "start":
    if record["load"] != "loaded":
        code = 5
    else:
        record["active"], record["since"] = "active", 1
json.dump(state, open(state_path, "w"))
sys.exit(code)
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


def _host(tmp_path: Path, *, load: str, active: str, since: int) -> dict[str, str]:
    """A shared home holding the thinker's unit, and a manager's view of it."""
    units = tmp_path / "home" / ".config" / "systemd" / "user"
    (units / "default.target.wants").mkdir(parents=True)
    (units / UNIT).write_text(
        f"[Unit]\nConditionHost={HOST}\n[Install]\nWantedBy=default.target\n", encoding="utf-8"
    )
    (units / "default.target.wants" / UNIT).symlink_to(units / UNIT)

    state = tmp_path / "state"
    state.mkdir()
    (state / "state.json").write_text(
        json.dumps({"unit": {"load": load, "active": active, "since": since}, "calls": []}),
        encoding="utf-8",
    )
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name, body in (("systemctl", _SYSTEMCTL), ("crontab", _CRONTAB), ("logger", _LOGGER)):
        (stubs / name).write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    (stubs / "flock").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (stubs / "hostname").write_text(f"#!/bin/sh\necho {HOST}\n", encoding="utf-8")
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    (tmp_path / "runtime").mkdir()
    return {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{stubs}:{os.environ['PATH']}",
        "STUB_STATE": str(state),
        "XDG_RUNTIME_DIR": str(tmp_path / "runtime"),
    }


def _run(env: dict[str, str], *arguments: str) -> None:
    done = subprocess.run(
        ["bash", str(SCRIPT), *arguments], env=env, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr


def _calls(env: dict[str, str]) -> list[list[str]]:
    state = json.loads((Path(env["STUB_STATE"]) / "state.json").read_text(encoding="utf-8"))
    return state["calls"]


def test_a_boot_that_never_read_the_unit_reloads_and_then_starts_the_thinker(
    tmp_path: Path,
) -> None:
    env = _host(tmp_path, load="not-found", active="inactive", since=0)

    _run(env, "run", NAME, UNIT)

    calls = _calls(env)
    assert ["daemon-reload"] in calls
    assert ["start", UNIT] in calls
    assert calls.index(["daemon-reload"]) < calls.index(["start", UNIT])


def test_a_thinker_somebody_stopped_after_it_ran_is_left_stopped(tmp_path: Path) -> None:
    env = _host(tmp_path, load="loaded", active="inactive", since=42)

    _run(env, "run", NAME, UNIT)

    assert ["start", UNIT] not in _calls(env)
    assert ["daemon-reload"] not in _calls(env)


def test_arming_twice_leaves_one_line_naming_the_thinker(tmp_path: Path) -> None:
    env = _host(tmp_path, load="loaded", active="active", since=42)

    _run(env, "arm", NAME, UNIT)
    _run(env, "arm", NAME, UNIT)

    lines = (Path(env["STUB_STATE"]) / "crontab").read_text(encoding="utf-8").splitlines()
    assert lines == [f"*/5 * * * * /bin/bash {SCRIPT} run {NAME} {UNIT} # {NAME}"]


def test_the_installer_arms_the_job_for_the_unit_it_writes() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert f'UNIT="{UNIT}"' in text
    arms = re.findall(r'after-boot\.sh" arm (\S+) "\$\{UNIT\}"\)', text)
    assert arms == [NAME], (
        f"install.sh arms the after-boot job as {arms}. Without exactly one, the "
        "thinker installed here does not come back after the next reboot."
    )


def test_the_installer_asks_whether_cron_can_run_the_job_before_writing_anything() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    check = text.find('after-boot.sh" check')
    first_write = text.find('mkdir -p "${ETC}" "${UNIT_DIR}"')

    assert check != -1
    assert first_write != -1
    assert check < first_write
