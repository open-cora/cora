"""Every placeholder in a unit template is one its installer fills in.

A template and the script that renders it are two files that have to move
together, and nothing else compares them. A placeholder added to one and
not the other ships a unit with a literal `@NAME@` where a path or a port
should be, which systemd accepts for everything it does not parse: the
service starts, and the setting is wrong rather than absent.

That has happened twice in this tree's deployments, once in each
direction. An installer documented a variable that the script shipping to
the host never forwarded, and a port line that a deployed unit carried was
one its template had no way to express, so re-running the installer erased
it and moved a server onto a port its clients were not searching.

The second direction is the one no test can reach from inside the
repository: a setting that exists only on a host is invisible here. This
checks the half that is visible, which is that the two tracked files agree.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]

PLACEHOLDER = re.compile(r"@[A-Z][A-Z0-9_]*@")

EXPECTED_TEMPLATES = 3
"""How many unit templates this project ships.

Pinned so that a rule ranging over nothing passes loudly rather than
quietly. A fourth service is a fourth row here.
"""


def _tracked(pattern: str) -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", pattern],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        check=True,
    )
    return [PROJECT / line for line in listed.stdout.split("\n") if line]


def _installer_for(template: Path) -> Path | None:
    for candidate in _tracked("infra/*/install*.sh"):
        if template.name in candidate.read_text(encoding="utf-8"):
            return candidate
    return None


def test_every_unit_template_has_an_installer_that_names_it() -> None:
    templates = _tracked("infra/*/*.service.in")

    assert len(templates) == EXPECTED_TEMPLATES, f"found {[t.name for t in templates]}"
    orphans = [t.name for t in templates if _installer_for(t) is None]
    assert not orphans, f"no installer renders {orphans}, so nothing fills their placeholders"


def test_every_placeholder_in_a_unit_template_is_one_its_installer_fills() -> None:
    unfilled: list[str] = []
    for template in _tracked("infra/*/*.service.in"):
        installer = _installer_for(template)
        assert installer is not None
        script = installer.read_text(encoding="utf-8")
        for name in sorted(set(PLACEHOLDER.findall(template.read_text(encoding="utf-8")))):
            if f"s|{name}|" not in script:
                unfilled.append(f"{template.name}: {name} is not substituted by {installer.name}")

    assert not unfilled, (
        "A unit would ship with the placeholder still in it, which systemd "
        "accepts as a literal value:\n    " + "\n    ".join(unfilled)
    )
