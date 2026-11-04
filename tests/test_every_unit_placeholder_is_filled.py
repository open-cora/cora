"""Every placeholder in a unit template is one its installer fills in.

A template and the script that renders it are two files that have to
move together, and nothing else compares them. A placeholder added to
one and not the other ships a unit with a literal `@NAME@` where a path
or a port should be, which systemd accepts for everything it does not
parse: the service starts, and the setting is wrong rather than absent.

That has happened twice in this tree's deployments, once in each
direction. An installer documented a variable that the script shipping
to the host never forwarded, and a port line a deployed unit carried was
one its template had no way to express, so re-running the installer
erased it and moved a server onto a port its clients were not searching.

## Why it is here and not in each project

`apps/conductor` already holds this rule for its own templates, because
a mirror has to carry its own. Three other projects ship units and none
of them did, so the same break was possible in all three and nothing
would have said so.

This is the tree-wide half: it ranges over every tracked template
wherever it sits, including the one under `beamlines/` that belongs to
no project at all. The conductor's copy stays, because its mirror is
extracted without this file beside it.

## What it cannot see

A setting that exists only on a host. If somebody edits an installed
unit by hand, nothing in this repository knows, and the next install
overwrites it. That half is unreachable from here and is the half that
caused the port incident.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

TREE = Path(__file__).resolve().parents[1]

PLACEHOLDER = re.compile(r"@[A-Z][A-Z0-9_]*@")

MINIMUM_TEMPLATES = 8
"""How few templates this may find before it is ranging over too little.

A floor rather than a pin, because the exact count is already pinned per
project and a second copy of that number here would be two things to
move for one change. What this guards is the pathspec: a glob that
stopped matching would pass every assertion below by checking nothing.
"""


def _tracked_templates() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.service.in"],
        cwd=TREE,
        capture_output=True,
        text=True,
        check=True,
    )
    return [TREE / line for line in listed.stdout.splitlines() if line]


def _installer_beside(template: Path) -> Path | None:
    """The script in the same directory that names this template."""
    for candidate in sorted(template.parent.glob("install*.sh")):
        if template.name in candidate.read_text(encoding="utf-8"):
            return candidate
    return None


def test_the_sweep_finds_the_templates_this_rule_is_meant_to_range_over() -> None:
    """The guard on the rule below, which is the whole point of the file."""
    found = _tracked_templates()
    assert len(found) >= MINIMUM_TEMPLATES, (
        f"Found {[t.name for t in found]}, which is fewer templates than this "
        "tree ships. The pathspec has stopped matching and the rule below is "
        "checking almost nothing."
    )
    orphans = [str(t.relative_to(TREE)) for t in found if _installer_beside(t) is None]
    assert not orphans, (
        f"No installer beside {orphans} names it, so nothing fills their "
        "placeholders and this rule cannot see them."
    )


def test_every_placeholder_in_every_unit_template_is_one_its_installer_fills() -> None:
    unfilled: list[str] = []
    for template in _tracked_templates():
        installer = _installer_beside(template)
        assert installer is not None
        script = installer.read_text(encoding="utf-8")
        for name in sorted(set(PLACEHOLDER.findall(template.read_text(encoding="utf-8")))):
            if f"s|{name}|" not in script:
                unfilled.append(
                    f"{template.relative_to(TREE)}: {name} is not substituted by {installer.name}"
                )

    assert not unfilled, (
        "A unit would ship with the placeholder still in it, which systemd "
        "accepts for anything it does not parse, so the service starts and the "
        "setting is wrong rather than missing:\n    " + "\n    ".join(unfilled)
    )
