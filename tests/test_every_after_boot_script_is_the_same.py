"""Every app that arms a return after a reboot ships the same script to do it.

`infra/deploy/after-boot.sh` is told by its installer which units are its
app's and which of them wait on a guard, so the same bytes serve every app
that installs `systemd --user` units on a shared home. Each mirror carries
its own copy, as it carries its own push script, and nothing in any project
compares them, because each project's suite enumerates only its own
directory. Each suite does run its own copy against a model of a user
manager; this is what makes those runs test one script rather than two that
happen to share a name.

It ranges over whoever has a copy rather than a list, so an app that gains
one later is covered without anybody remembering to add it here.

## The name each installer arms it under

The job leaves a line in a crontab on the host, and that crontab is the
account's, shared with whatever else runs at that beamline. So the name an
installer gives the job is spelled the way every other name this system
leaves on a host is: `cora-`, the app, and then what it is. That name marks
the line the next deploy replaces, so two apps sharing one would replace
each other's.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests._tracked import TREE_ROOT

if TYPE_CHECKING:
    from pathlib import Path

RELATIVE = "infra/deploy/after-boot.sh"
"""Where an app keeps the script, under its own root."""

MINIMUM = 4
"""How many copies must exist before comparing them means anything.

A rule ranging over one file passes by agreeing with itself, and one
ranging over none passes louder. Four, because every app's deploy
installer arms the job today, so a copy that goes missing fails here
rather than leaving the rest to agree among themselves.
"""

ARMED = re.compile(r'after-boot\.sh" arm (\S+)')
"""The name an installer arms the job under."""


def _copies() -> dict[str, Path]:
    apps = TREE_ROOT / "apps"
    return {
        app.name: app / RELATIVE for app in sorted(apps.iterdir()) if (app / RELATIVE).is_file()
    }


def test_enough_apps_arm_a_return_after_a_reboot_for_the_comparison_to_mean_anything() -> None:
    found = _copies()
    assert len(found) >= MINIMUM, (
        f"Found {sorted(found)} carrying {RELATIVE}, and comparing fewer than "
        f"{MINIMUM} copies proves nothing. If an app stopped arming one, say so "
        "here rather than leaving a rule that cannot fail."
    )


def test_every_copy_of_the_after_boot_script_is_byte_identical() -> None:
    contents = {app: path.read_bytes() for app, path in _copies().items()}
    assert len(set(contents.values())) == 1, (
        f"{RELATIVE} differs between {sorted(contents)}: "
        f"{ {app: len(body) for app, body in contents.items()} }.\n"
        "These are duplicated rather than shared, so nothing but this check "
        "keeps them in step. Everything app-specific arrives on the command "
        "line its installer writes, so a difference between them is a fix "
        "somebody made in one copy and did not carry to the others."
    )


def test_every_app_with_a_copy_arms_it_from_its_installer_under_its_own_name() -> None:
    for app, path in _copies().items():
        installer = path.parent / "install.sh"
        names = ARMED.findall(installer.read_text(encoding="utf-8"))
        assert names == [f"cora-{app}-after-boot"], (
            f"{app}'s installer arms the after-boot job as {names}. It has to arm "
            f"it once, as cora-{app}-after-boot: the name marks the crontab line "
            "the next deploy replaces, so a copy armed under nothing is a script "
            "no host runs, and two apps under one name replace each other."
        )
