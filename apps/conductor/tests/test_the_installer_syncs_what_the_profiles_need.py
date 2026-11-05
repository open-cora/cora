"""A deployment that names a profile gets the library that profile imports.

The package declares no core dependencies, so every install is a set of
extras. Three are always needed. The two that are not, `transfer` and
`compute`, belong to the profiles under `infra/`, and a deployment that
names one in its run table and is then synced without it gets a
conductor that will not import its own engine.

That failure is loud at startup and mute about its cause: the message
names a module that will not import, and nothing connects it to a list
of extras in a shell script the operator did not write.

So the installer reads the configuration it was handed and adds them
when a profile is named. It adds both rather than matching each profile
to its own library, because telling them apart would mean the installer
knowing which module imports which SDK, which is the profile's business
and changes without telling it.

## Why this is a test and not a comment

The same mistake was made twice in one evening, once here and once in
the watcher's installer next door, each time by writing a fixed list of
extras beside a feature that had just become optional. A fixed list is
the natural thing to write and it is wrong the moment anything is
conditional.
"""

from __future__ import annotations

from pathlib import Path

INSTALLER = Path(__file__).resolve().parents[1] / "infra" / "deploy" / "install.sh"

ALWAYS = ("--extra service", "--extra epics", "--extra sim")
"""What every conductor needs, profiles or not."""

FOR_PROFILES = ("--extra transfer", "--extra compute")
"""What the two shipped profiles import, named in pyproject as extras."""


def test_the_installer_still_builds_a_virtualenv_this_rule_can_read() -> None:
    """The guard, so a rewrite does not leave this checking nothing."""
    script = INSTALLER.read_text(encoding="utf-8")

    assert "uv sync" in script, (
        f"{INSTALLER.name} no longer syncs a virtualenv, so the checks below "
        "compare against a step that is not there."
    )


def test_every_conductor_gets_the_extras_it_always_needs() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    missing = [extra for extra in ALWAYS if extra not in script]

    assert not missing, f"{INSTALLER.name} no longer installs {missing}"


def test_a_configuration_naming_a_profile_also_gets_the_profile_libraries() -> None:
    script = INSTALLER.read_text(encoding="utf-8")
    missing = [extra for extra in FOR_PROFILES if extra not in script]

    assert not missing, (
        f"{INSTALLER.name} does not install {missing}, so a deployment naming "
        "a run profile would be synced without the library that profile "
        "imports. The conductor then refuses to start on a module that will "
        "not import, and nothing says the extras were the reason."
    )
    assert "PROFILES" in script, (
        "the profile extras are present but nothing makes them conditional, "
        "so every beamline installs two Globus SDKs to not use them."
    )
