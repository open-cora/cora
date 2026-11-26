"""A soft IOC this project ships starts only when nothing else answers its names.

`infra/deploy/serve-alone.sh` is the ExecStart of the citation records and
of both simulators: it asks whether a control record answers and whether
any of the unit's names already does, and either becomes the server or
exits saying why not. Two servers answering one name is a race whose loser
is silent, and the installers' own refusal runs only when somebody
installs, so this is what holds at a boot, a restart and the after-boot
job alike.

These run the script against the session's soft IOCs, which serve real
names over real Channel Access on the loopback. caget is replaced by a
stand-in on caproto's own client, because EPICS base is not installed
here; it answers as caget does, zero for a record that answers and not
zero for one that does not, and writes down what it was asked and with
which settings. The server is a stand-in that records that it ran.

## Each unit, as its installer would write it

The second half renders each of the three templates the way its installer
does, with the control and the names read out of that installer's own
assignments, and runs the rendered ExecStart up to its `--`. So a unit that
stopped passing through the check, or passed it names other than the ones
its installer's preflight asks about, fails here.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests import _ioc, _tomoscan_ioc

pytestmark = [pytest.mark.channel_access, pytest.mark.usefixtures("tomoscan_ioc")]

INFRA = Path(__file__).resolve().parents[1] / "infra"
SCRIPT = INFRA / "deploy" / "serve-alone.sh"

CONTROL = f"{_tomoscan_ioc.PREFIX}ServerRunning"
SERVED = f"{_tomoscan_ioc.PREFIX}KeeperExecutionId"
FREE = ("conductor-free-test:KeeperExecutionId", "conductor-free-test:KeeperStepId")
SILENT = "conductor-silent-test:ServerRunning"


def _code(name: str) -> int:
    found = re.findall(rf"^{name}=(\d+)$", SCRIPT.read_text(encoding="utf-8"), re.M)
    assert len(found) == 1, f"serve-alone.sh no longer sets {name} once"
    return int(found[0])


REFUSED = _code("REFUSED")
NOT_YET = _code("NOT_YET")

_CAGET = """
import os, sys, time
from caproto.sync.client import read

arguments = sys.argv[1:]
wait = float(arguments[1]) if arguments[:1] == ["-w"] else 0.0
name = arguments[-1]
with open(os.environ["STAND_IN_LOG"], "a") as log:
    log.write(
        f"start {name} {time.monotonic()} wait={wait} "
        f"port={os.environ.get('EPICS_CA_SERVER_PORT', '-')} "
        f"list={os.environ.get('EPICS_CA_ADDR_LIST', '-')}\\n"
    )
try:
    read(name, timeout=1.0, repeater=False)
    answered = True
except Exception:
    answered = False
with open(os.environ["STAND_IN_LOG"], "a") as log:
    log.write(f"end {name} {time.monotonic()}\\n")
sys.exit(0 if answered else 1)
"""
"""caget, as far as the check uses it: whether a record answers, within a while.

It shortens the wait to a second, because a record that is absent costs
its whole wait and these tests ask about several. The wait it was asked
for is written down instead, so the installers' own is still checked.
"""


@dataclass(frozen=True)
class Started:
    """What one run of the check did."""

    code: int
    said: str
    server_ran: bool
    server_environment: dict[str, str]
    asked: list[str]


class Station:
    """The check's surroundings: a stand-in caget, its settings, and a stand-in server."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.caget = root / "caget"
        self.caget.write_text(f"#!{sys.executable}\n{_CAGET}", encoding="utf-8")
        self.caget.chmod(0o755)
        self.server = root / "server"
        self.server.write_text('#!/bin/sh\nenv > "$SERVER_RAN"\n', encoding="utf-8")
        self.server.chmod(0o755)
        self.client_env = root / "client.env"
        self.settings(caget=self.caget)

    def settings(self, *, caget: Path) -> None:
        """Client settings as an installer captures them from the shell it ran in."""
        self.client_env.write_text(
            f"CAGET={caget}\n"
            f"EPICS_CA_ADDR_LIST={os.environ['EPICS_CA_ADDR_LIST']}\n"
            "EPICS_CA_AUTO_ADDR_LIST=NO\n",
            encoding="utf-8",
        )

    def start(self, *line: str, unit_environment: dict[str, str] | None = None) -> Started:
        ran = self.root / "server-ran"
        log = self.root / "asked"
        for stale in (ran, log):
            stale.unlink(missing_ok=True)
        done = subprocess.run(
            ["bash", *line],
            env={
                "PATH": os.environ["PATH"],
                "HOME": str(self.root),
                "SERVER_RAN": str(ran),
                "STAND_IN_LOG": str(log),
                **(unit_environment or {}),
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        environment: dict[str, str] = {}
        if ran.exists():
            for entry in ran.read_text(encoding="utf-8").splitlines():
                key, _, value = entry.partition("=")
                environment[key] = value
        return Started(
            code=done.returncode,
            said=done.stdout + done.stderr,
            server_ran=ran.exists(),
            server_environment=environment,
            asked=log.read_text(encoding="utf-8").splitlines() if log.exists() else [],
        )

    def check(
        self, control: str, *names: str, unit_environment: dict[str, str] | None = None
    ) -> Started:
        return self.start(
            str(SCRIPT),
            str(self.client_env),
            control,
            *names,
            "--",
            str(self.server),
            unit_environment=unit_environment,
        )


@pytest.fixture
def station(tmp_path: Path) -> Station:
    return Station(tmp_path)


def test_a_server_whose_names_nothing_answers_is_started(station: Station) -> None:
    started = station.check(CONTROL, *FREE)

    assert started.code == 0, started.said
    assert started.server_ran


def test_a_server_whose_name_already_answers_is_refused_and_not_started(station: Station) -> None:
    started = station.check(CONTROL, FREE[0], SERVED)

    assert started.code == REFUSED, started.said
    assert not started.server_ran, "a second server was started beside one already answering"
    assert SERVED in started.said
    assert FREE[0] not in started.said.split("already served by something else:")[1]


def test_a_silent_control_concludes_nothing_and_asks_to_be_tried_again(station: Station) -> None:
    started = station.check(SILENT, *FREE)

    assert started.code == NOT_YET, started.said
    assert not started.server_ran
    assert not [line for line in started.asked if FREE[0] in line], (
        "the names were asked about although nothing proved a silent one meant absent"
    )


def test_a_caget_that_is_not_there_yet_asks_to_be_tried_again(station: Station) -> None:
    station.settings(caget=station.root / "not-yet-mounted" / "caget")

    started = station.check(CONTROL, *FREE)

    assert started.code == NOT_YET, started.said
    assert not started.server_ran


def test_client_settings_that_are_missing_refuse_rather_than_serve_unchecked(
    station: Station,
) -> None:
    station.client_env.unlink()

    started = station.check(CONTROL, *FREE)

    assert started.code == REFUSED, started.said
    assert not started.server_ran


def test_a_unit_line_with_no_separator_before_the_server_is_refused(station: Station) -> None:
    started = station.start(
        str(SCRIPT), str(station.client_env), CONTROL, *FREE, str(station.server)
    )

    assert started.code == REFUSED, started.said
    assert not started.server_ran


def test_the_question_uses_the_installers_settings_and_the_server_keeps_the_units(
    station: Station,
) -> None:
    unit = {"EPICS_CA_SERVER_PORT": "5999", "EPICS_CA_ADDR_LIST": "192.0.2.1"}

    started = station.check(CONTROL, *FREE, unit_environment=unit)

    assert started.code == 0, (
        f"the unit's own settings reached the question and hid the station: {started.said}"
    )
    starts = [line for line in started.asked if line.startswith("start ")]
    assert starts
    assert all("port=- " in line for line in starts), "the server's port reached caget"
    assert all(f"list={os.environ['EPICS_CA_ADDR_LIST']}" in line for line in starts)
    assert all("wait=5.0" in line for line in starts), "the installers wait five seconds"
    assert started.server_environment["EPICS_CA_SERVER_PORT"] == "5999", (
        "the server did not start with the unit's own environment"
    )


def test_every_name_is_asked_about_at_once_rather_than_in_turn(station: Station) -> None:
    names = (*FREE, "conductor-free-test:StartScan")

    started = station.check(CONTROL, *names)

    assert started.code == 0, started.said
    begun = {
        line.split()[1]: float(line.split()[2])
        for line in started.asked
        if line.startswith("start ")
    }
    ended = {
        line.split()[1]: float(line.split()[2]) for line in started.asked if line.startswith("end ")
    }
    assert max(begun[name] for name in names) < min(ended[name] for name in names), (
        "one name was asked about only after another had been answered, so a start "
        "waits one timeout per name instead of one"
    )


_UNITS = {
    "citation records": (INFRA / "bridge", "install-citation-ioc.sh"),
    "simulated TomoScan": (INFRA / "sim", "install-tomoscan.sh"),
    "simulated motors": (INFRA / "sim", "install-motors.sh"),
}
"""Each unit that starts through the check, by its installer."""


def _installed_names(installer: Path, inputs: dict[str, str], root: Path) -> tuple[str, str]:
    """CONTROL and NAMES as the installer assigns them, given its inputs.

    Everything before the installer defines `say` only assigns, so it is run
    as written and asked what it assigned, rather than spelled out again
    here and left to drift from the preflight that asks the same question.
    It runs from a file of its own so that the installer's reading of its
    own location has a location to read.
    """
    text = installer.read_text(encoding="utf-8")
    assignments = root / "assignments.sh"
    assignments.write_text(
        text[: text.index("\nsay() {")] + '\nprintf "%s\\n" "${CONTROL}" "${NAMES}"\n',
        encoding="utf-8",
    )
    done = subprocess.run(
        ["bash", str(assignments)],
        env={"PATH": os.environ["PATH"], "HOME": str(root), **inputs},
        capture_output=True,
        text=True,
        check=True,
    )
    control, names = done.stdout.splitlines()[-2:]
    return control, names


def _start_line(
    template: Path, station: Station, control: str, names: str, prefix: str
) -> list[str]:
    line = next(
        line.removeprefix("ExecStart=")
        for line in template.read_text(encoding="utf-8").splitlines()
        if line.startswith("ExecStart=")
    )
    for placeholder, value in {
        "@SERVE_ALONE@": str(SCRIPT),
        "@CLIENT_ENV@": str(station.client_env),
        "@CONTROL@": control,
        "@NAMES@": names,
        "@PREFIX@": prefix,
    }.items():
        line = line.replace(placeholder, value)
    return shlex.split(line)


def _template(directory: Path, installer: str) -> Path:
    text = (directory / installer).read_text(encoding="utf-8")
    rendered = re.findall(r"\$\{SCRIPT_DIR\}/([A-Za-z0-9._-]+\.service\.in)", text)
    assert len(rendered) == 1, f"{installer} renders {rendered}"
    return directory / rendered[0]


def _inputs(prefix: str) -> dict[str, str]:
    return {
        "BEAMLINE": "7-bm",
        "PREFIX": prefix,
        "CONTROL": f"{_ioc.PREFIX}mtr1",
        "SERVER_PORT": "5999",
        "DATA_ROOT": "/nowhere",
    }


@pytest.mark.parametrize("unit", sorted(_UNITS))
def test_each_unit_starts_through_the_check_with_its_installers_names(
    unit: str, station: Station
) -> None:
    directory, installer = _UNITS[unit]
    template = _template(directory, installer)
    control, names = _installed_names(directory / installer, _inputs("x:"), station.root)

    line = _start_line(template, station, control, names, "x:")

    assert line[:3] == [str(SCRIPT), str(station.client_env), control], line
    separator = line.index("--")
    assert line[3:separator] == names.split(), (
        f"the {unit} unit asks about {line[3:separator]}, and its installer's "
        f"preflight asks about {names.split()}"
    )
    assert line[separator + 1 :], f"the {unit} unit starts nothing after its check"
    assert f"RestartPreventExitStatus={REFUSED}" in template.read_text(encoding="utf-8"), (
        f"the {unit} unit would restart after a refusal and refuse again every "
        "fifteen seconds, burying the reason"
    )


@pytest.mark.parametrize(
    ("unit", "prefix"),
    [
        ("citation records", _tomoscan_ioc.PREFIX),
        ("simulated TomoScan", _tomoscan_ioc.PREFIX),
        ("simulated motors", _ioc.PREFIX),
    ],
)
def test_each_unit_refuses_to_start_where_its_names_are_already_served(
    unit: str, prefix: str, station: Station
) -> None:
    directory, installer = _UNITS[unit]
    control, names = _installed_names(directory / installer, _inputs(prefix), station.root)
    line = _start_line(_template(directory, installer), station, control, names, prefix)

    started = station.start(*line[: line.index("--") + 1], str(station.server))

    assert started.code == REFUSED, started.said
    assert not started.server_ran


@pytest.mark.parametrize("unit", sorted(_UNITS))
def test_each_unit_starts_where_its_control_answers_and_its_names_are_free(
    unit: str, station: Station
) -> None:
    """The citation unit's control is its own prefix's, which nothing here serves.

    So each unit is rendered with a control this suite does serve, and with a
    prefix nothing serves, which is the free station every one of them
    expects to find.
    """
    directory, installer = _UNITS[unit]
    _, names = _installed_names(
        directory / installer, _inputs("conductor-free-test:"), station.root
    )
    line = _start_line(
        _template(directory, installer), station, CONTROL, names, "conductor-free-test:"
    )

    started = station.start(*line[: line.index("--") + 1], str(station.server))

    assert started.code == 0, started.said
    assert started.server_ran


@pytest.mark.parametrize("unit", sorted(_UNITS))
def test_each_installer_captures_its_client_settings_between_its_preflight_and_its_unit(
    unit: str,
) -> None:
    directory, installer = _UNITS[unit]
    text = (directory / installer).read_text(encoding="utf-8")
    preflight = text.find('say "preflight   ')
    captured = text.find('} > "${CLIENT_ENV}"')
    rendered = text.find(f'"${{SCRIPT_DIR}}/{_template(directory, installer).name}" >')

    assert "printf 'CAGET=%s\\n' \"${CAGET}\"" in text, f"{installer} never records its caget"
    assert "env | grep '^EPICS_CA_'" in text, f"{installer} never records its client settings"
    assert -1 < preflight < captured < rendered, (
        f"{installer} captures the settings its unit asks with before its preflight "
        "has shown they see the station, or after the unit that reads them is written"
    )
