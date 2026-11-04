"""The two agreements no database holds, checked without needing a host.

`verify_hosts.py` reads files on four machines, so its real control is a
run against hosts whose state is known by other means. That cannot run
in a suite. What can is the comparison itself, with the host's answer
supplied, and that is where every branch below lives.

The ones worth having are the ones that have already cost something. A
routine the operation register does not declare refuses every dispatch
at that beamline, which is what four Refused scans turned out to be.

The sharper one is a confirmed run step whose scopes name one station
while the conductor drives another. It is the opposite of a refusal and
it was reported as a refusal for a while, which is worse than reporting
nothing: `control.writable` reaches `EpicsControl` and fences set steps,
and nothing anywhere compares a run step's scopes to the engine. So such
a step takes a claim that protects nothing and runs on the prefix.

Two of these checks had no honest coverage before. The writable fence
was exercised only through run steps, which it does not govern, and no
confirmed procedure in any register has a set step at all, so the branch
that does the governing had never run. It is driven from a register
written here for the purpose.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

import verify_hosts
from verify_hosts import Unit, arming, check, listed, section, units

BEAMLINES = Path(__file__).parents[1]


ARMED = (
    "cora-conductor.service|enabled|active|a-host\n"
    "cora-motor-sim.service|enabled|inactive|another-host\n"
)
"""An account whose units are armed once and pinned to one host each.

The hostnames are placeholders. A real one would be a facility
coordinate, which `tests/` refuses in a tracked file.
"""


def _answer(
    routines: str = '["tomography_scan"]',
    writable: str = '["corasim7bm:"]',
    prefix: str = "corasim7bm:TomoScan:",
    revision: str = "be682985f8a7acf86eb029f9130e984333410b07",
    token: str = "",
    unit_lines: str = ARMED,
) -> str:
    prefix_line = f'prefix = "{prefix}"\n' if prefix else ""
    return (
        f"== conductor.revision\n{revision}\n"
        f"== reporter.revision\n{revision}\n"
        f"== conductor.config\n"
        f'beamline = "7-bm"\n{token}routines = {routines}\n'
        f"{prefix_line}writable = {writable}\n"
        f"== units\n{unit_lines}"
    )


def _a_register(root: Path, beamline: str, procedures: str) -> Path:
    """A tree of two files, for a shape no real register carries.

    The registers hold what this facility actually runs, and two of the
    branches here are about what it does not: a confirmed set step, and
    a confirmed step that drives no device. Reaching those by editing a
    real register would mean a test that passes because of a row
    somebody could remove for unrelated reasons.
    """
    (root / "operations.toml").write_text(
        '[[operation]]\nname = "tomography_scan"\n\n'
        "[operation.parameters_schema]\n"
        '"$schema" = "https://json-schema.org/draft/2020-12/schema"\n'
        'type = "object"\n',
        encoding="utf-8",
    )
    station = root / beamline
    station.mkdir()
    (station / "procedures.toml").write_text(
        f'beamline = "{beamline}"\n\n{procedures}', encoding="utf-8"
    )
    return root


HostSays = Callable[..., None]


@pytest.fixture
def host_says(monkeypatch: pytest.MonkeyPatch) -> HostSays:
    """Answer for a host, so every branch runs without one."""

    def install(output: str, code: int = 0) -> None:
        def answer(target: str, script: str, ssh_opts: list[str]) -> tuple[int, str]:
            return code, output

        monkeypatch.setattr(verify_hosts, "ask", answer)

    return install


def test_a_host_matching_the_registers_reports_no_disagreement(host_says: HostSays) -> None:
    host_says(_answer())
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert report.problems == []
    assert report.total == 0


def test_a_routine_the_operation_register_does_not_declare_is_reported(host_says: HostSays) -> None:
    """The failure that produced four Refused scans.

    The conductor refuses a routine it was not told about, so a rename
    landing in the register and not on the hosts refuses every dispatch.
    """
    host_says(_answer(routines='["tomo_scan"]'))
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert any("tomo_scan" in p and "does not declare" in p for p in report.problems)


def test_a_confirmed_set_step_outside_the_writable_fence_is_reported(
    host_says: HostSays, tmp_path: Path
) -> None:
    """The fence that is really a fence, driven for the first time.

    `control.writable` is handed to `EpicsControl`, which refuses a
    write outside it, so for a set step the word refused is accurate.
    """
    tree = _a_register(
        tmp_path,
        "7-bm",
        '[[procedure]]\nname = "Rotate"\nconfirmed = true\n\n'
        '  [[procedure.step]]\n  kind = "set"\n  record = "7bmb:m1"\n  to = 0.0\n',
    )
    host_says(_answer(writable='["corasim7bm:"]'))
    report = check("7-bm", "host", tree, [], None)

    assert any("7bmb:m1" in p and "does not cover" in p for p in report.problems)


def test_a_confirmed_run_step_claiming_another_station_is_reported(host_says: HostSays) -> None:
    """The near miss this check was rewritten for.

    A deployment repointed off its simulator and the procedure was not,
    so a row reading as a simulation drove a station. Nothing refused
    it and nothing could: a run step's scopes are compared to nothing.
    """
    host_says(_answer(prefix="7bm:TomoScan:"))
    report = check("7-bm", "host", BEAMLINES, [], None)

    assert any("corasim7bm:" in p and "7bm:TomoScan:" in p for p in report.problems)


def test_a_run_step_claiming_another_station_is_not_reported_as_refused(
    host_says: HostSays,
) -> None:
    """The word that made the old message worse than silence.

    A reader who saw refused concluded the system was already stopping
    the thing it was running, so the message has to say the opposite.
    """
    host_says(_answer(prefix="7bm:TomoScan:"))
    report = check("7-bm", "host", BEAMLINES, [], None)

    claim = next(p for p in report.problems if "corasim7bm:" in p)
    assert "not refused" in claim
    assert "the scan is real" in claim


def test_a_confirmed_run_step_claiming_the_station_it_drives_is_not_reported(
    host_says: HostSays,
) -> None:
    """A claim is compared to the station, not to the whole prefix.

    No procedure claims the scan server itself, so comparing against
    `corasim7bm:TomoScan:` whole would report every honest row here.
    """
    host_says(_answer(prefix="corasim7bm:TomoScan:"))
    report = check("7-bm", "host", BEAMLINES, [], None)

    assert not any("corasim7bm:" in p for p in report.problems)


def test_a_conductor_naming_no_prefix_is_reported_rather_than_passed(
    host_says: HostSays,
) -> None:
    """Silence here is not agreement, for the reason it never is.

    Reading a missing prefix as nothing to check would pass exactly the
    deployment whose configuration this cannot see.
    """
    host_says(_answer(prefix=""))
    report = check("7-bm", "host", BEAMLINES, [], None)

    assert any("names no run.prefix" in p for p in report.problems)


def test_a_confirmed_step_that_drives_no_device_is_not_measured_against_a_prefix(
    host_says: HostSays, tmp_path: Path
) -> None:
    """Work that happens at another facility has no station to agree with."""
    tree = _a_register(
        tmp_path,
        "7-bm",
        '[[procedure]]\nname = "Move a dataset"\nconfirmed = true\n\n'
        '  [[procedure.step]]\n  kind = "run"\n  operation = "tomography_scan"\n'
        "  drives_no_device = true\n",
    )
    host_says(_answer(prefix="7bm:TomoScan:"))
    report = check("7-bm", "host", tree, [], None)

    assert not any("Move a dataset" in p for p in report.problems)


def test_an_inline_token_in_a_host_configuration_is_reported(host_says: HostSays) -> None:
    host_says(_answer(token='token = "a-jwt"\n'))
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert any("itself a credential" in p for p in report.problems)


def test_a_host_at_another_revision_is_reported(host_says: HostSays) -> None:
    host_says(_answer(revision="0123456789abcdef0123456789abcdef01234567"))
    report = check("7-bm", "host", BEAMLINES, [], "be682985f8a7acf86eb029f9130e984333410b07")
    assert len([p for p in report.problems if "the tree is at" in p]) == 2


def test_a_host_carrying_no_revision_is_reported_rather_than_passed(host_says: HostSays) -> None:
    host_says(_answer(revision=""))
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert len([p for p in report.problems if "carries no REVISION" in p]) == 2


def test_a_host_that_cannot_be_asked_is_a_disagreement_and_not_a_pass(host_says: HostSays) -> None:
    """An unreachable host is the one answer that must not read as agreement.

    Every other check here is a comparison against something the host
    said. A host that said nothing has nothing to compare, and counting
    that as agreement is how a fleet check reports clean while a machine
    is down.
    """
    host_says("", code=255)
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert report.unreachable is not None
    assert report.total == 1


def test_a_configuration_naming_no_routines_is_reported(host_says: HostSays) -> None:
    host_says(
        "== conductor.revision\nbe68298\n== reporter.revision\nbe68298\n"
        '== conductor.config\nbeamline = "7-bm"\nwritable = ["corasim7bm:"]\n'
    )
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert any("names no routines" in p for p in report.problems)


def test_an_inline_array_yields_its_names() -> None:
    assert listed('["a", "b"]') == ["a", "b"]
    assert listed("[]") == []


def test_a_named_block_is_read_and_a_missing_one_is_empty() -> None:
    out = "== one\nalpha\n== two\nbeta\ngamma\n"
    assert section(out, "one").strip() == "alpha"
    assert section(out, "two").split() == ["beta", "gamma"]
    assert section(out, "three") == ""


def test_a_unit_running_without_being_enabled_is_reported(host_says: HostSays) -> None:
    """The state that reads as healthy and does not survive a reboot.

    Removing an enable symlink neither stops the unit nor writes to the
    journal, so a simulator unarmed this way keeps answering until its
    host next reboots and then is simply gone. Three beamlines sat in
    this state and `is-active` reported every one of them as fine.
    """
    host_says(_answer(unit_lines="cora-motor-sim.service|disabled|active|a-host\n"))
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert any("does not bring it back, and it is running now" in p for p in report.problems)


def test_a_unit_with_no_condition_host_is_reported(host_says: HostSays) -> None:
    """The hazard enabling would create without the pin.

    One unit directory is mounted by every host in the account, so an
    enabled unit with nothing to narrow it starts a copy on each host
    that lingers. For a simulator that is several IOCs serving one
    prefix, and for a client several conductors claiming one beamline.
    """
    host_says(_answer(unit_lines="cora-conductor.service|enabled|active|\n"))
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert any("carries no ConditionHost" in p for p in report.problems)


def test_an_account_holding_no_cora_units_is_reported(host_says: HostSays) -> None:
    host_says(_answer(unit_lines=""))
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert any("restores nothing" in p for p in report.problems)


def test_an_armed_and_pinned_account_reports_no_disagreement() -> None:
    assert arming(units(f"== units\n{ARMED}")) == []


def test_a_unit_line_the_probe_could_not_fill_is_skipped_rather_than_guessed() -> None:
    assert units("== units\ncora-motor-sim.service|enabled\n") == []


def test_every_field_of_a_unit_line_is_read() -> None:
    assert units("== units\ncora-reporter.service|enabled|active|a-host\n") == [
        Unit(name="cora-reporter.service", enabled="enabled", active="active", condition="a-host")
    ]
