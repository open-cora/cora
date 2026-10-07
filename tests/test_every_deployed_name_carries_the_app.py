"""Everything an app leaves on a host is named `cora-` and then the app.

A deployment writes into two directories it does not own: a source
directory in the account's home, and a unit in `~/.config/systemd/user`.
Neither namespace belongs to this system. The accounts are the facility's,
shared with whatever else runs at that beamline, and the measurement is
not close: the three homes deployed into hold 83, 176 and 329 entries,
and `ors_data_organizer.service` sits beside ours in one of the unit
directories.

So the prefix says whose a name is, the app's own directory name says
which of ours, and together they make `cora-*` select this system and
nothing else in a place full of strangers.

## Why this is a test and not a convention

It was a convention and it did not hold. The keeper installed three units
unprefixed once, and its installer still carries the loop that retires
them, because a host that ran that version would otherwise enable two
units per service: two API processes on one port, two containers reaching
for one data directory.

The spellings sit in places no suite reads together: a default in
`push.sh`, a literal in each installer, and the template filenames. Each
project's suite enumerates only its own directory, so a project can drift
from its siblings and stay green, which three of them did.

## Two scopes, because two claims are not the same claim

The rules below come in pairs. One pair reads `infra/deploy` under `apps/`
and asks whether a name carries the app, which only means something where
an app owns the unit. The other reads every tracked template anywhere and
asks the two weaker questions that hold with no app in sight: that a
template is named for the unit it becomes, and that the unit is prefixed.

Separating them is what lets the second pair reach a unit no app ships.
Three templates sat outside the first scope and all three were misnamed:
two simulators under `infra/sim`, and the keeper id records, which install
from `beamlines/` because they attach to a station's own prefix. The rule
written to stop exactly this drift could not see any of them.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from tests._tracked import TREE_ROOT

if TYPE_CHECKING:
    from pathlib import Path

DEPLOY = "infra/deploy"
"""Where an app keeps what installs it, under its own root."""

PREFIX = "cora-"
"""What marks a name as this system's in a directory that is not."""

MINIMUM = 2
"""How many apps must deploy before comparing their names means anything.

A rule ranging over one passes by agreeing with itself, and one ranging
over none passes louder.
"""

INSTALLED = re.compile(r'(?:UNIT="|\$\{UNIT_DIR\}/)([A-Za-z0-9._@-]+\.service)\b')
"""A unit an installer writes, wherever it spells the name out.

Two shapes because the apps differ: one that installs a single unit
assigns it to `UNIT` first, and the keeper, which installs three, names
each at the point it renders it. A name reaching the directory through a
variable is not matched and is not meant to be, which is what keeps the
keeper's retirement loop out of this: those three are the old names, and
the whole point of that loop is that they are wrong.
"""

RENDERED = re.compile(r"\$\{SCRIPT_DIR\}/([A-Za-z0-9._@-]+\.service\.in)")
"""A template an installer reads, named relative to its own directory."""


def _deploying_apps() -> dict[str, Path]:
    apps = TREE_ROOT / "apps"
    return {
        app.name: app / DEPLOY
        for app in sorted(apps.iterdir())
        if (app / DEPLOY / "install.sh").is_file()
    }


def _installer(directory: Path) -> str:
    return (directory / "install.sh").read_text(encoding="utf-8")


def test_enough_apps_deploy_this_way_for_the_comparison_to_mean_anything() -> None:
    found = _deploying_apps()
    assert len(found) >= MINIMUM, (
        f"Found {sorted(found)} carrying {DEPLOY}/install.sh, and fewer than "
        f"{MINIMUM} proves nothing about a shared convention."
    )


def test_the_installers_name_units_in_a_shape_this_rule_can_see() -> None:
    """The guard on the two patterns above, which are the whole check.

    A regex that has stopped matching reports a clean tree in exactly the
    voice of a clean tree. Both of these have to find something in every
    app, or the rules below are passing over nothing.
    """
    for app, directory in _deploying_apps().items():
        body = _installer(directory)
        assert INSTALLED.findall(body), (
            f"{app}'s installer names no unit this rule recognises, so nothing "
            "below is checking it. Either it stopped writing one or it spells "
            "the name a third way, and this pattern has to learn it."
        )
        assert RENDERED.findall(body), (
            f"{app}'s installer reads no unit template this rule recognises."
        )


def test_every_unit_an_installer_writes_is_named_for_its_app() -> None:
    for app, directory in _deploying_apps().items():
        for unit in INSTALLED.findall(_installer(directory)):
            assert unit.startswith(f"{PREFIX}{app}"), (
                f"{app}'s installer writes {unit} into a directory the facility "
                f"also keeps units in. It has to begin {PREFIX}{app} so that it "
                "says whose it is and which of ours, and so that stopping this "
                f"system is `systemctl --user stop '{PREFIX}*'` and not a list "
                "somebody maintains."
            )


def test_every_unit_template_is_named_for_the_app_that_ships_it() -> None:
    for app, directory in _deploying_apps().items():
        for template in sorted(directory.glob("*.service.in")):
            assert template.name.startswith(f"{PREFIX}{app}"), (
                f"{app} ships {template.name}, which is not the name of the unit "
                f"it becomes. The path already says which app it belongs to, so "
                "this buys nothing there. It buys that one search for a unit "
                "name finds the template, the installer and the prose together, "
                "rather than two of the three."
            )


def test_every_template_an_installer_names_is_a_file_that_exists() -> None:
    """The half of a rename that is easy to leave undone.

    Renaming the file and not the reference, or the reverse, survives
    every other check in this tree and fails at the host, after the copy,
    with whoever ran it standing at the machine.
    """
    for app, directory in _deploying_apps().items():
        for named in RENDERED.findall(_installer(directory)):
            assert (directory / named).is_file(), (
                f"{app}'s installer renders {named}, which is not in {DEPLOY}."
            )


def test_every_template_an_app_ships_is_one_its_installer_renders() -> None:
    for app, directory in _deploying_apps().items():
        rendered = set(RENDERED.findall(_installer(directory)))
        for template in sorted(directory.glob("*.service.in")):
            assert template.name in rendered, (
                f"{app} ships {template.name} and its installer renders "
                f"{sorted(rendered)}, so that file reaches every host and is "
                "read by nothing."
            )


def test_the_push_script_defaults_the_remote_directory_to_the_prefixed_app() -> None:
    """The source directory, which is the other half of what lands on a host.

    Spelled in the one script all four share, so it is checked once. It
    is checked at all because the default is what makes the convention
    hold without anybody passing a path, and the day it was overridden
    for one app, that app's deployment stopped being findable where the
    other three are.
    """
    for app, directory in _deploying_apps().items():
        push = directory / "push.sh"
        if not push.is_file():
            continue
        body = push.read_text(encoding="utf-8")
        assert 'REMOTE="${REMOTE:-cora-${APP}}"' in body, (
            f"{app}'s push.sh does not default the remote directory to "
            f"{PREFIX} and the app's own name."
        )


TRACKED_TEMPLATES_MINIMUM = 6
"""How many unit templates the tree-wide enumeration must find.

The same guard the app-scoped rules carry, for the same reason: a
pathspec that has stopped matching reports a clean tree in the voice of
a clean tree. Set below the current count so that adding a service does
not fail this, and far enough above zero that losing the pathspec does.
"""


def _tracked_templates() -> list[Path]:
    """Every unit template this tree tracks, inside a project or outside one.

    Deliberately not `tests._tracked`, whose enumerators exclude `apps/`
    so each project can scan itself. This rule compares projects against
    each other and against what no project owns, so it is one of the few
    here that has to see all of them at once.
    """
    listed = subprocess.run(
        ["git", "ls-files", "*.service.in"],
        cwd=TREE_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [TREE_ROOT / line for line in listed.stdout.splitlines() if line]


def _installer_beside(template: Path) -> Path | None:
    """The script in the same directory that names this template."""
    for candidate in sorted(template.parent.glob("install*.sh")):
        if template.name in candidate.read_text(encoding="utf-8"):
            return candidate
    return None


def test_the_tree_wide_sweep_finds_the_templates_it_is_meant_to_range_over() -> None:
    """The guard on the two rules below, which are the whole point of this file."""
    found = _tracked_templates()
    assert len(found) >= TRACKED_TEMPLATES_MINIMUM, (
        f"Found {[t.name for t in found]} tracked unit templates, which is "
        "fewer than this tree has. The pathspec has stopped matching and the "
        "rules below are ranging over almost nothing."
    )
    orphans = [str(t.relative_to(TREE_ROOT)) for t in found if _installer_beside(t) is None]
    assert not orphans, (
        f"No installer beside {orphans} names it, so this rule cannot tell what "
        "unit those templates become and is silently skipping them."
    )


def test_every_unit_template_is_named_for_the_unit_it_becomes() -> None:
    """Wherever it sits, including the one directory no app owns.

    The app-scoped twin of this asks for more and reaches less. This asks
    only that the two spellings match, which is what makes one search for
    a unit name seen on a host find the template that produced it.
    """
    for template in _tracked_templates():
        installer = _installer_beside(template)
        assert installer is not None
        written = set(INSTALLED.findall(installer.read_text(encoding="utf-8")))
        becomes = template.name.removesuffix(".in")
        assert becomes in written, (
            f"{template.relative_to(TREE_ROOT)} renders into {sorted(written)}, "
            f"so nothing on a host is called {becomes}. A reader who sees a unit "
            "and greps for it finds the installer and not the file it came from."
        )


def test_every_unit_an_installer_writes_anywhere_carries_the_prefix() -> None:
    """The weaker half of the app rule, which is the half that holds everywhere.

    `beamlines/keeper-ids` installs into a facility account and belongs to
    no app, so it can carry no app name. It can still say whose it is, and
    that is what keeps stopping this system one glob rather than a list.
    """
    for template in _tracked_templates():
        installer = _installer_beside(template)
        assert installer is not None
        for unit in sorted(set(INSTALLED.findall(installer.read_text(encoding="utf-8")))):
            assert unit.startswith(PREFIX), (
                f"{installer.relative_to(TREE_ROOT)} writes {unit} into a "
                f"directory the facility also keeps units in, without {PREFIX} "
                "in front of it to say whose it is."
            )
