"""Every installer that writes a unit arms a return after a reboot, with one script.

`after-boot.sh` is told by its installer which units are its own and which
of them wait on a guard, so the same bytes serve every installer that puts a
`systemd --user` unit in a shared home. Each mirror carries its own copy in
`infra/deploy`, as it carries its own push script, and so does the keeper id
records' directory under `beamlines/`, which ships on its own. Nothing in
any project compares them, because each project's suite enumerates only its
own directory. Each suite does run its own copy against a model of a user
manager; this is what makes those runs test one script rather than several
that happen to share a name.

It ranges over whatever carries a copy and whatever renders a unit, rather
than over a list, so an installer added later is covered without anybody
remembering to add it here.

## The name each installer arms it under

The job leaves a line in a crontab on the host, and that crontab is the
account's, shared with whatever else runs at that beamline. So the job is
named the way every other name this system leaves on a host is, after the
unit it brings back: the unit's name with -after-boot in place of .service.
That name marks the line the next install replaces, so two installers
sharing one would replace each other's, and naming it for a unit the
installer itself renders is what keeps it one installer's alone.

## Before anything changes

Each installer asks whether the host can run the job before it changes
anything. A host that cannot reboots into a unit that never comes back, and
an installer that found out halfway would leave half a deployment behind.
The keeper id records are held to that here and nowhere else, because they
belong to no project. Every app checks its own installers as well, so that
a mirror carries the rule.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from tests._tracked import TREE_ROOT

if TYPE_CHECKING:
    from pathlib import Path

COPY = "after-boot.sh"

MINIMUM = 5
"""How many copies must exist before comparing them means anything.

A rule ranging over one file passes by agreeing with itself, and one
ranging over none passes louder. Five: one in each app's deploy directory,
and one beside the keeper id records, so a copy that goes missing fails
here rather than leaving the rest to agree among themselves.
"""

EXPECTED_INSTALLERS = 10
"""How many tracked installers render a unit, and so have a job to arm.

The four apps' deploy installers, the turner, the citation records, the two
simulators, the watcher, and the keeper id records.
"""

ARM = re.compile(r'(?:after-boot\.sh|\$\{AFTER_BOOT\})" arm (\S+)')
"""The name an installer arms the job under."""

CHECK = re.compile(r'(?:after-boot\.sh|\$\{AFTER_BOOT\})" check \|\| exit 1$')

RENDERED = re.compile(r"\$\{SCRIPT_DIR\}/([A-Za-z0-9._@-]+)\.service\.in")
"""A unit template an installer reads, named relative to its own directory."""

CHANGES = (
    re.compile(r"^\s*mkdir -p\b"),
    re.compile(r"^\s*systemctl --user (?:stop|daemon-reload|enable|restart)\b"),
    re.compile(r"\buv pip install\b|\s-m pip install\b"),
    re.compile(r"\buv sync\b"),
    re.compile(r'> "\$\{APP_DIR\}/REVISION"'),
)
"""The lines that change a host: a directory, a unit's state, a package, a revision."""


def _tracked_scripts() -> list[Path]:
    """Every tracked shell script in the tree, the apps included.

    Through git rather than a glob, so a file git has never seen is absent
    here too. The apps are in scope on purpose: comparing their copies is the
    whole of this rule, and no project can do it for itself.
    """
    listed = subprocess.run(
        ["git", "ls-files", "*.sh"],
        cwd=TREE_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(TREE_ROOT / name for name in listed)


def _copies() -> dict[str, Path]:
    return {
        str(path.relative_to(TREE_ROOT)): path for path in _tracked_scripts() if path.name == COPY
    }


def _installers() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in _tracked_scripts():
        text = path.read_text(encoding="utf-8")
        if RENDERED.search(text):
            found[str(path.relative_to(TREE_ROOT))] = text
    return found


def _first(lines: list[str], patterns: tuple[re.Pattern[str], ...]) -> int | None:
    for number, line in enumerate(lines):
        if line.lstrip().startswith("#"):
            continue
        if any(pattern.search(line) for pattern in patterns):
            return number
    return None


def test_enough_installers_arm_a_return_after_a_reboot_for_the_comparison_to_mean_anything() -> (
    None
):
    found = _copies()
    assert len(found) >= MINIMUM, (
        f"Found {sorted(found)} carrying {COPY}, and comparing fewer than "
        f"{MINIMUM} copies proves nothing. If something stopped arming one, say "
        "so here rather than leaving a rule that cannot fail."
    )


def test_every_copy_of_the_after_boot_script_is_byte_identical() -> None:
    contents = {name: path.read_bytes() for name, path in _copies().items()}
    assert len(set(contents.values())) == 1, (
        f"{COPY} differs between {sorted(contents)}: "
        f"{ {name: len(body) for name, body in contents.items()} }.\n"
        "These are duplicated rather than shared, so nothing but this check "
        "keeps them in step. Everything installer-specific arrives on the "
        "command line its installer writes, so a difference between them is a "
        "fix somebody made in one copy and did not carry to the others."
    )


def test_the_tree_still_has_the_installers_these_rules_range_over() -> None:
    found = _installers()
    assert len(found) == EXPECTED_INSTALLERS, (
        f"found {sorted(found)} rendering a unit. Raise the count when an "
        "installer is added, which is also the moment to confirm it arms the job."
    )


def test_every_installer_arms_the_job_once_under_the_name_of_a_unit_it_renders() -> None:
    for name, text in _installers().items():
        jobs = ARM.findall(text)
        assert len(jobs) == 1, (
            f"{name} arms the after-boot job {jobs}. Without exactly one arm, the "
            "unit it installs does not come back after the next reboot whose "
            "user manager started before the home."
        )
        assert jobs[0].endswith("-after-boot")
        assert jobs[0].removesuffix("-after-boot") in RENDERED.findall(text), (
            f"{name} arms the job as {jobs[0]}, which is not named for a unit it "
            "renders. The name marks the crontab line the next install replaces, "
            "so it has to be one installer's alone."
        )


def test_no_two_installers_arm_the_job_under_one_name() -> None:
    jobs = [job for text in _installers().values() for job in ARM.findall(text)]
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
            f"has already changed the host on line {change + 1}"
        )
