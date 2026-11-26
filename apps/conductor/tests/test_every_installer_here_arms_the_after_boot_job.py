"""Every installer here arms the after-boot job, once, under the name of a unit it writes.

Five installers in this project write a unit into the account's shared home,
and each of those units stays down after a boot whose user manager came up
before the home was mounted. `infra/deploy/after-boot.sh` is the repair, and
each installer arms it as a crontab line on the host it installs on.

The job is named for the unit it brings back: the unit's name with
-after-boot in place of .service. That name marks the line the next install
replaces, so it has to belong to one installer alone, and naming it for a
unit the installer itself renders is what makes it so.

Each installer also asks whether the host can run the job before it changes
anything, because a host that cannot reboots into a unit that never comes
back, and an installer that found out halfway would leave half a deployment
behind.

Which units wait on a guard is a decision, so it is a table here and not a
pattern. The conductor's own installer arms every conductor on the host,
each with its guard, through a list this cannot read, and
`test_the_after_boot_job_brings_the_conductor_back.py` runs that block as
written instead.
"""

from __future__ import annotations

import re

from tests._tracked import PROJECT_ROOT, tracked_files

EXPECTED_INSTALLERS = 5
"""The conductor, the turner, the citation records and the two simulators."""

ARMED_AS_DECIDED: dict[str, str] = {
    "infra/turner/install-turner.sh": '"${UNIT}=${GUARD}"',
    "infra/bridge/install-citation-ioc.sh": '"${UNIT}"',
    "infra/sim/install-motors.sh": '"${UNIT}"',
    "infra/sim/install-tomoscan.sh": '"${UNIT}"',
}
"""What each installer arms beside the job's name, the conductor's own aside.

The turner waits on its guard, because its return dispatches the next step
of every running pursuit however long it was away. The other three come
back bare: what could go wrong on their return is a second server for a
name, which is as likely when a boot starts them as when the job does.
"""

DEPLOY_INSTALLER = "infra/deploy/install.sh"

ARM = re.compile(r'(?:after-boot\.sh|\$\{AFTER_BOOT\})" arm (\S+) (.*)\)"$', re.M)
CHECK = re.compile(r'(?:after-boot\.sh|\$\{AFTER_BOOT\})" check \|\| exit 1$')
RENDERED = re.compile(r"\$\{SCRIPT_DIR\}/([A-Za-z0-9._@-]+)\.service\.in")

CHANGES = (
    re.compile(r"^\s*mkdir -p\b"),
    re.compile(r"^\s*systemctl --user (?:stop|daemon-reload|enable|restart)\b"),
    re.compile(r"\buv pip install\b|\s-m pip install\b"),
    re.compile(r"\buv sync\b"),
    re.compile(r'> "\$\{APP_DIR\}/REVISION"'),
)
"""The lines that change a host: a directory, a unit's state, a package, a revision."""


def _installers() -> dict[str, str]:
    return {
        str(path.relative_to(PROJECT_ROOT)): path.read_text(encoding="utf-8")
        for path in sorted(tracked_files())
        if path.relative_to(PROJECT_ROOT).match("infra/*/install*.sh")
    }


def _arms(text: str) -> list[tuple[str, str]]:
    return ARM.findall(text)


def _first(lines: list[str], patterns: tuple[re.Pattern[str], ...]) -> int | None:
    for number, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if any(pattern.search(line) for pattern in patterns):
            return number
    return None


def test_this_project_still_has_the_installers_these_rules_range_over() -> None:
    found = _installers()

    assert len(found) == EXPECTED_INSTALLERS, f"found {sorted(found)}"
    assert set(found) == {*ARMED_AS_DECIDED, DEPLOY_INSTALLER}, (
        "an installer is missing from the table of what each one arms, so "
        "whether its unit waits on a guard has not been decided"
    )


def test_every_installer_arms_the_job_once_under_the_name_of_a_unit_it_renders() -> None:
    for name, text in _installers().items():
        arms = _arms(text)
        assert len(arms) == 1, f"{name} arms the after-boot job {len(arms)} times, not once"
        job = arms[0][0]
        assert job.endswith("-after-boot"), f"{name} arms the job as {job}"
        assert job.removesuffix("-after-boot") in RENDERED.findall(text), (
            f"{name} arms the job as {job}, which is not named for any unit it "
            "renders. The name marks the crontab line the next install replaces, "
            "so a name another installer could arm replaces that installer's line."
        )


def test_no_two_installers_arm_the_job_under_one_name() -> None:
    jobs = [arm[0] for text in _installers().values() for arm in _arms(text)]

    assert len(jobs) == len(set(jobs)), f"two installers share a job name: {sorted(jobs)}"


def test_every_installer_asks_whether_cron_can_run_the_job_before_it_changes_anything() -> None:
    for name, text in _installers().items():
        lines = text.splitlines()
        check = _first(lines, (CHECK,))
        change = _first(lines, CHANGES)

        assert check is not None, f"{name} never asks whether this host can run the job"
        assert change is not None, f"{name} changes nothing these patterns recognise"
        assert check < change, (
            f"{name} asks whether cron can run the job on line {check + 1}, after it "
            f"has already changed the host on line {change + 1}, so a refusal "
            "leaves half a deployment behind"
        )


def test_each_installer_arms_its_unit_bare_or_with_its_guard_as_decided() -> None:
    installers = _installers()
    for name, armed in ARMED_AS_DECIDED.items():
        assert [arm[1] for arm in _arms(installers[name])] == [armed], (
            f"{name} no longer arms {armed} beside the job's name"
        )
