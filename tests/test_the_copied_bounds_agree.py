"""One bound, declared by the keeper and copied into a client's script.

`apps/keeper/src/keeper/shared/identifier.py` sets how long the value half
of an external reference may be, and the keeper refuses a longer one.
`apps/reporter/scripts/collect_nodes.py` sorts candidate keys by whether
they fit that bound, and it holds its own copy of the number because the
environment it runs in cannot install the keeper.

Nothing else compares the two. Each project's suite enumerates its own
directory on purpose, per the mirror rule, so the keeper's tests cannot see
the script and the reporter's cannot see the keeper. The script's own prose
claimed a check that did exist, in a spike, which is neither project and
ships with neither: from inside either repository the copy was unguarded,
and a reader following the claim found nothing to follow.

Drift here is quiet rather than loud. The script goes on reporting that a
candidate key fits, the keeper goes on refusing it, and the disagreement
surfaces as a registration rejected at a beamline for a reason the tool
that chose the key said was fine.

This is the only check that reads both, which is why it lives here rather
than in either project.

## Why the numbers are read rather than imported

Importing would mean this tier installing both projects, and the tier
deliberately installs neither. What is being compared is an integer
literal either way.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TREE = Path(__file__).resolve().parents[1]

BOUND = "IDENTIFIER_VALUE_MAX_LENGTH"
"""The name both files hold the number under.

The same spelling in both, so a rename in either makes this test range
over nothing. That is why each side is checked for presence before the
two are compared.
"""

DECLARED = TREE / "apps" / "keeper" / "src" / "keeper" / "shared" / "identifier.py"
COPIED = TREE / "apps" / "reporter" / "scripts" / "collect_nodes.py"


def _bound_in(module: Path) -> int | None:
    """The integer the module binds to `BOUND`, or None if it binds none."""
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        match node:
            case ast.Assign(targets=[ast.Name(id=name)], value=ast.Constant(value=int() as size)):
                if name == BOUND:
                    return size
            case ast.AnnAssign(target=ast.Name(id=name), value=ast.Constant(value=int() as size)):
                if name == BOUND:
                    return size
            case _:
                continue
    return None


@pytest.mark.parametrize("module", (DECLARED, COPIED), ids=lambda p: p.name)
def test_a_side_of_the_comparison_still_declares_the_bound(module: Path) -> None:
    """Guard the lookup, so the comparison below cannot pass vacuously."""
    assert _bound_in(module) is not None, (
        f"{module.name} no longer binds {BOUND} to an integer literal. Renaming "
        "it on either side makes the comparison below range over nothing, which "
        "is the failure this test exists to prevent rather than to cause."
    )


def test_the_copy_matches_the_bound_the_keeper_enforces() -> None:
    declared, copied = _bound_in(DECLARED), _bound_in(COPIED)
    assert copied == declared, (
        f"the keeper refuses a value over {declared} characters and the script "
        f"sorts candidate keys against {copied}. A key the script calls short "
        "enough is then rejected at registration, and the tool that chose it "
        "said it would fit."
    )
