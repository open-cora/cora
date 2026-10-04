"""A number written beside "outward seams" is one the module can produce.

The count at the head of `seams` is the first thing a reader of this
package meets, and it is repeated wherever something else describes the
family. Nothing read either side of that, so both sides drifted: adding
or removing a seam is a change to a module, and the prose about it is in
a different file that the same change has no reason to open.

Found by counting rather than by reading. Three such numbers were wrong
across this tree on one afternoon, one of them written an hour earlier
by the change that made it wrong.

The rule is narrow on purpose. It governs the exact phrase "N outward
seams" and nothing else, because the word seam appears in ordinary prose
beside ordinary numbers all through this package, and a check that tried
to judge those would be guessing. A new way of spelling the same claim
escapes this, which is why the occurrence count is pinned below: a
rewording that leaves the rule matching nothing fails rather than
passes.
"""

from __future__ import annotations

import ast
import re

import pytest

from tests._tracked import (
    PROJECT_ROOT,
    tracked_prose_files,
    tracked_source_files,
    tracked_test_files,
)

_SPELLED: dict[int, str] = {
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
}

_CLAIM = re.compile(r"\b(\w+) outward seams\b")

EXPECTED_CLAIMS = 2
"""How many places spell the count out.

Pinned because a rule that matches nothing passes. Raise it when a new
place states the count, never to quiet a red run.
"""


def _declared_seams() -> int:
    """How many seams `seams` declares, counted off its syntax tree.

    Protocols and nothing else. The values that travel through a seam
    live in the same module and are not seams, which is the distinction
    the prose is making when it says outward.
    """
    tree = ast.parse((PROJECT_ROOT / "src" / "conductor" / "seams.py").read_text(encoding="utf-8"))
    return sum(
        1
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Protocol" for base in node.bases)
    )


def _claims() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(tracked_source_files() | tracked_test_files() | tracked_prose_files()):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in _CLAIM.finditer(line):
                found.append((str(path.relative_to(PROJECT_ROOT)), number, match.group(1)))
    return found


def test_the_count_this_module_declares_has_a_word_for_it() -> None:
    """A count past the table reads as a passing test and is not one."""
    assert _declared_seams() in _SPELLED


def test_every_place_spelling_the_seam_count_spells_the_one_the_module_declares() -> None:
    spelled = _SPELLED[_declared_seams()]
    wrong = [(where, line, said) for where, line, said in _claims() if said.lower() != spelled]
    assert not wrong, f"the module declares {spelled}, and these say otherwise: {wrong}"


def test_the_scan_finds_every_place_the_count_is_spelled_out() -> None:
    found = _claims()
    assert len(found) == EXPECTED_CLAIMS, (
        f"found {len(found)} places spelling the seam count and expected {EXPECTED_CLAIMS}: {found}"
    )


@pytest.mark.parametrize("claim", _claims(), ids=lambda c: f"{c[0]}:{c[1]}")
def test_a_spelled_count_is_a_word_this_table_knows(claim: tuple[str, int, str]) -> None:
    _where, _line, said = claim
    assert said.lower() in _SPELLED.values(), (
        f"{said!r} is not a number word here, so the comparison above would pass by accident"
    )
