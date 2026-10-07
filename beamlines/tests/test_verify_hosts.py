"""The two agreements no database holds, checked without needing a host.

`verify_hosts.py` reads files on four machines, so its real control is a
run against hosts whose state is known by other means. That cannot run
in a suite. What can is the comparison itself, with the host's answer
supplied, and that is where every branch below lives.

The two worth having are the ones that have already cost something. A
routine the operation register does not declare refuses every dispatch
at that beamline, which is what four Refused scans turned out to be. A
confirmed procedure claiming outside `control.writable` is the same
failure pointed the other way, and the fence is the second of the two
guards standing between a drafted routine and real hardware.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

import verify_hosts
from verify_hosts import check, listed, section

BEAMLINES = Path(__file__).parents[1]


def _answer(
    routines: str = '["tomography_scan"]',
    writable: str = '["corasim7bm:"]',
    revision: str = "be682985f8a7acf86eb029f9130e984333410b07",
    token: str = "",
) -> str:
    return (
        f"== conductor.revision\n{revision}\n"
        f"== reporter.revision\n{revision}\n"
        f"== conductor.config\n"
        f'beamline = "7-bm"\n{token}routines = {routines}\nwritable = {writable}\n'
    )


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


def test_a_confirmed_procedure_claiming_outside_the_fence_is_reported(host_says: HostSays) -> None:
    """The safety property, stated as a check.

    A writable narrower than what a procedure claims refuses the step. A
    writable wider than the simulator prefix is how a procedure reaches
    the beamline's own records, and nothing else looks at it.
    """
    host_says(_answer(writable='["corasimSOMETHINGELSE:"]'))
    report = check("7-bm", "host", BEAMLINES, [], None)
    assert any("does not cover" in p for p in report.problems)


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
