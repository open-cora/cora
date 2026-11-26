"""The keeper id records start only when nothing else answers their names.

`beamlines/keeper-ids/` serves two records under a station's own prefix, and
its intended end is the station's database gaining them. From that day, a
second server beside the first would file scans against the wrong work. The
install script refuses then, but only when somebody installs, so the unit's
ExecStart is `serve-alone.sh`, which asks the same question at every start.

The apps run that script against a soft IOC. This tier has none, so it runs
the copy beside the records with a caget that answers for a fixed set of
names, which is enough to prove what belongs to these records alone: that
the unit passes through the check, with the two names the install script's
preflight asks about, and refuses where they are served.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from typing import TYPE_CHECKING

from tests._tracked import TREE_ROOT

if TYPE_CHECKING:
    from pathlib import Path

RECORDS = TREE_ROOT / "beamlines" / "keeper-ids"
INSTALLER = RECORDS / "install.sh"
TEMPLATE = RECORDS / "cora-keeper-ids.service.in"
SCRIPT = RECORDS / "serve-alone.sh"

INPUTS = {
    "BEAMLINE": "7-bm",
    "P": "7bm:",
    "R": "TomoScan:",
    "CONTROL": "7bm:TomoScan:ServerRunning",
}


def _code(name: str) -> int:
    found = re.findall(rf"^{name}=(\d+)$", SCRIPT.read_text(encoding="utf-8"), re.M)
    assert len(found) == 1, f"serve-alone.sh no longer sets {name} once"
    return int(found[0])


def _installed(tmp_path: Path) -> tuple[str, str]:
    """CONTROL and NAMES as the install script assigns them, run as written."""
    text = INSTALLER.read_text(encoding="utf-8")
    assignments = tmp_path / "assignments.sh"
    assignments.write_text(
        text[: text.index("\nsay() {")] + '\nprintf "%s\\n" "${CONTROL}" "${NAMES}"\n',
        encoding="utf-8",
    )
    done = subprocess.run(
        ["bash", str(assignments)],
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), **INPUTS},
        capture_output=True,
        text=True,
        check=True,
    )
    control, names = done.stdout.splitlines()[-2:]
    return control, names


def _start(tmp_path: Path, *, answering: set[str]) -> tuple[int, bool, str]:
    """Run the unit's ExecStart up to its server, with a caget answering for `answering`."""
    control, names = _installed(tmp_path)
    caget = tmp_path / "caget"
    listed = tmp_path / "answering"
    listed.write_text("".join(f"{name}\n" for name in answering), encoding="utf-8")
    caget.write_text(f'#!/bin/sh\ngrep -qxF -- "$3" "{listed}"\n', encoding="utf-8")
    caget.chmod(0o755)
    client_env = tmp_path / "client.env"
    client_env.write_text(f"CAGET={caget}\nEPICS_CA_AUTO_ADDR_LIST=NO\n", encoding="utf-8")
    server = tmp_path / "server"
    ran = tmp_path / "server-ran"
    server.write_text(f'#!/bin/sh\ntouch "{ran}"\n', encoding="utf-8")
    server.chmod(0o755)

    line = next(
        line.removeprefix("ExecStart=")
        for line in TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.startswith("ExecStart=")
    )
    for placeholder, value in {
        "@SERVE_ALONE@": str(SCRIPT),
        "@CLIENT_ENV@": str(client_env),
        "@CONTROL@": control,
        "@NAMES@": names,
    }.items():
        line = line.replace(placeholder, value)
    words = shlex.split(line)
    done = subprocess.run(
        ["bash", *words[: words.index("--") + 1], str(server)],
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return done.returncode, ran.exists(), done.stdout + done.stderr


def test_the_unit_starts_through_the_check_with_the_names_its_preflight_asks_about(
    tmp_path: Path,
) -> None:
    control, names = _installed(tmp_path)
    line = next(
        line
        for line in TEMPLATE.read_text(encoding="utf-8").splitlines()
        if line.startswith("ExecStart=")
    )

    assert line.startswith(
        "ExecStart=@SERVE_ALONE@ @CLIENT_ENV@ @CONTROL@ @NAMES@ -- @SOFTIOC@ "
    ), line
    assert control == INPUTS["CONTROL"]
    assert names.split() == ["7bm:TomoScan:KeeperExecutionId", "7bm:TomoScan:KeeperStepId"]
    assert re.search(
        r"^for record in \$\{NAMES\}; do$", INSTALLER.read_text(encoding="utf-8"), re.M
    ), "the preflight no longer asks about the names the unit's every start asks about"


def test_a_refusal_is_not_restarted_into_a_loop_that_buries_it() -> None:
    assert f"RestartPreventExitStatus={_code('REFUSED')}" in TEMPLATE.read_text(encoding="utf-8")


def test_the_install_script_captures_its_client_settings_before_it_writes_the_unit() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    preflight = text.find("for record in ${NAMES}; do")
    captured = text.find('} > "${CLIENT_ENV}"')
    rendered = text.find('"${SCRIPT_DIR}/cora-keeper-ids.service.in" > "${UNIT_DIR}/${UNIT}"')

    assert "printf 'CAGET=%s\\n' \"${CAGET}\"" in text
    assert "env | grep '^EPICS_CA_'" in text
    assert -1 < preflight < captured < rendered, (
        "the client settings are captured before the preflight has shown they see "
        "the beamline, or after the unit that reads them was written"
    )


def test_the_records_start_where_the_control_answers_and_neither_name_does(
    tmp_path: Path,
) -> None:
    code, ran, said = _start(tmp_path, answering={INPUTS["CONTROL"]})

    assert code == 0, said
    assert ran


def test_the_records_refuse_to_start_where_either_name_is_already_served(tmp_path: Path) -> None:
    code, ran, said = _start(tmp_path, answering={INPUTS["CONTROL"], "7bm:TomoScan:KeeperStepId"})

    assert code == _code("REFUSED"), said
    assert not ran, "a second server was started beside one already answering"
    assert "7bm:TomoScan:KeeperStepId" in said


def test_the_records_wait_for_a_control_that_does_not_answer_yet(tmp_path: Path) -> None:
    code, ran, said = _start(tmp_path, answering=set())

    assert code == _code("NOT_YET"), said
    assert not ran
