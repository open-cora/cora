"""Every soft IOC that refuses a second server refuses with the same script.

`serve-alone.sh` is the ExecStart of every unit that serves records under
names a station may also serve: the citation records and the two simulators
through the conductor's copy, and the keeper id records through the copy
beside them, which ships from `beamlines/` on its own. Nothing in any
project compares the two, because each project's suite enumerates only its
own directory. The conductor runs its copy against a soft IOC and this tier
runs the other with a stand-in; this is what makes those two runs test one
script.
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from tests._tracked import TREE_ROOT

if TYPE_CHECKING:
    from pathlib import Path

COPY = "serve-alone.sh"

MINIMUM = 2
"""The conductor's copy and the keeper id records' copy.

A rule ranging over one file passes by agreeing with itself, so a copy
that goes missing fails here rather than leaving the other to agree alone.
"""

STARTS_THROUGH = re.compile(r"^ExecStart=@SERVE_ALONE@ ", re.M)


def _tracked(pattern: str) -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", pattern],
        cwd=TREE_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted(TREE_ROOT / name for name in listed)


def _copies() -> dict[str, bytes]:
    return {
        str(path.relative_to(TREE_ROOT)): path.read_bytes()
        for path in _tracked("*.sh")
        if path.name == COPY
    }


def test_enough_units_refuse_a_second_server_for_the_comparison_to_mean_anything() -> None:
    assert len(_copies()) >= MINIMUM, f"found {sorted(_copies())} carrying {COPY}"


def test_every_copy_of_the_serve_alone_script_is_byte_identical() -> None:
    contents = _copies()
    assert len(set(contents.values())) == 1, (
        f"{COPY} differs between {sorted(contents)}. These are duplicated rather "
        "than shared, so nothing but this check keeps them in step, and a fix "
        "made in one copy and not carried to the other is a station whose second "
        "server one unit refuses and the other starts."
    )


def test_every_unit_that_starts_through_it_has_an_installer_that_names_a_copy() -> None:
    templates = [
        path for path in _tracked("*.service.in") if STARTS_THROUGH.search(path.read_text("utf-8"))
    ]
    assert len(templates) == 4, f"found {[path.name for path in templates]} starting through it"
    for template in templates:
        installers = [
            path
            for path in template.parent.glob("install*.sh")
            if template.name in path.read_text(encoding="utf-8")
        ]
        assert len(installers) == 1, f"no single installer renders {template.name}"
        assert f"/{COPY}" in installers[0].read_text(encoding="utf-8"), (
            f"{installers[0].name} renders {template.name}, which starts through "
            f"{COPY}, and never says where a copy of it is"
        )
