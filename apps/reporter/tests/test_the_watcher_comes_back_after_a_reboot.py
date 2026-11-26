"""After its host reboots, every watcher there comes back without anybody starting it.

The watcher installs from `infra/watcher/install-watcher.sh` and leaves a
unit in the same shared home as the reporter's, so it stays down after the
same kind of boot, and arms the same job: `infra/deploy/after-boot.sh`, whose
behavior this suite runs beside this file.

What is the watcher's own is which units the line names. A host may run two
watchers under INSTANCE, each with a unit of its own, and the crontab line is
one per host, so the installer arms every watcher pinned to the host rather
than the one it just installed. That is a choice made by reading the unit
directory when the installer runs, so the block that makes it is run here as
written, under bash, with the script it calls replaced by a stand-in that
records what it was asked. The unit names it is handed are read from the
installer's own spelling of them, so renaming the unit in one place and not
the other fails here.

No guard: a watcher that comes back finishes the record of work that has
already happened, and moves nothing.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "infra" / "watcher" / "install-watcher.sh"

HOST = "this-host"

_UNIT_SPELLINGS = re.compile(r'UNIT="([^"]+\.service)"')
_BLOCK = ('echo "After a reboot"', 'echo "Done.')


def _deployed_names() -> tuple[str, str]:
    spelled = _UNIT_SPELLINGS.findall(INSTALLER.read_text(encoding="utf-8"))
    assert len(spelled) == 2, f"the installer spells its unit {spelled}, not plain and per instance"
    plain, per_instance = spelled
    assert "${INSTANCE}" in per_instance
    return plain, per_instance


def _arm(tmp_path: Path, *, pinned: dict[str, str]) -> list[str] | None:
    """Run the arming block with `pinned` in the home, and return what the job was armed with."""
    text = INSTALLER.read_text(encoding="utf-8")
    start = text.find(_BLOCK[0])
    end = text.find(_BLOCK[1], start)
    assert start != -1, f"{INSTALLER.name} has no {_BLOCK[0]!r}, so there is no arming block"
    assert end != -1, f"nothing follows the arming block; expected {_BLOCK[1]!r}"

    watcher, deploy, units = tmp_path / "watcher", tmp_path / "deploy", tmp_path / "units"
    for directory in (watcher, deploy, units):
        directory.mkdir()
    for unit, where in pinned.items():
        (units / unit).write_text(f"[Unit]\nConditionHost={where}\n", encoding="utf-8")
    armed = tmp_path / "armed"
    stand_in = deploy / "after-boot.sh"
    stand_in.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > "{armed}"\necho "a crontab line"\n', encoding="utf-8"
    )
    stand_in.chmod(0o755)

    prelude = "\n".join(
        (
            "set -euo pipefail",
            "say() { printf '  %s\\n' \"$*\"; }",
            "die() { printf 'refused: %s\\n' \"$*\" >&2; exit 1; }",
            f"SCRIPT_DIR={shlex.quote(str(watcher))}",
            f"UNIT_DIR={shlex.quote(str(units))}",
            f"DEPLOY_HOST={HOST}",
            "",
        )
    )
    block = tmp_path / "arming.sh"
    block.write_text(prelude + text[start:end], encoding="utf-8")
    done = subprocess.run(
        ["bash", str(block)],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return armed.read_text(encoding="utf-8").splitlines() if armed.exists() else None


def test_the_watcher_installer_arms_every_watcher_pinned_here_and_nothing_else(
    tmp_path: Path,
) -> None:
    plain, per_instance = _deployed_names()
    scans = per_instance.replace("${INSTANCE}", "scans")
    elsewhere = per_instance.replace("${INSTANCE}", "moves")

    armed = _arm(
        tmp_path,
        pinned={plain: HOST, scans: HOST, elsewhere: "another-host", "other.service": HOST},
    )

    assert armed is not None, "the block never armed the job"
    verb, _, *units = armed
    assert verb == "arm"
    assert sorted(units) == sorted([plain, scans]), (
        f"armed {units}. Every watcher pinned to this host belongs on the line, "
        "and nothing pinned elsewhere or belonging to another service does"
    )


def test_the_watcher_installer_arms_the_job_under_its_units_name_with_no_guard(
    tmp_path: Path,
) -> None:
    plain, _ = _deployed_names()

    armed = _arm(tmp_path, pinned={plain: HOST})

    assert armed is not None, "the block never armed the job"
    assert armed[1] == plain.removesuffix(".service") + "-after-boot", (
        f"the job is armed as {armed[1]}, and the name has to be the unit's own "
        "followed by -after-boot: it marks the crontab line the next install "
        "replaces, and a name another installer could arm replaces that line"
    )
    assert not [unit for unit in armed[2:] if "=" in unit], "a watcher's return waits on nothing"


def test_the_watcher_installer_asks_whether_cron_can_run_the_job_before_it_changes_anything() -> (
    None
):
    text = INSTALLER.read_text(encoding="utf-8")
    check = text.find('after-boot.sh" check || exit 1')
    changes = {
        "sync the virtualenv": text.find("uv sync --locked"),
        "make the unit directory": text.find('mkdir -p "${UNIT_DIR}"'),
    }

    assert check != -1, "install-watcher.sh never asks whether this host can run the job"
    assert all(offset != -1 for offset in changes.values()), changes
    assert all(check < offset for offset in changes.values()), (
        "install-watcher.sh asks whether cron can run the job only after it has "
        "started changing the host, so a refusal leaves half a deployment behind"
    )
