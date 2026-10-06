"""The coordinate rule exists five times, and only this compares them.

`test_no_facility_coordinates.py` is carried by the checkout and by each of
the four projects, because a mirror runs its own suite and a rule that lives
only out here would not reach it. That duplication is the same trade the
licence and the push script make, and it fails the same way: each project's
suite enumerates its own directory, so no project can see that its copy has
drifted from anyone else's.

It drifted within an hour of being written. The rule was repaired in the
checkout's copy and in none of the four, so four projects went on shipping a
home-path check whose samples could not fail. Nothing went red, because every
suite agreed with itself.

## What this proves, and the larger thing it does not

It proves the copies agree. It never proves that what they agree on is
enough, and the difference is not academic: the rule shipped with an address
book listing host names and no accounts, so an uppercase account name reached
four published repositories through five copies that were identical and
identically incomplete. This check passed honestly throughout, because it had
nothing to disagree about.

That is a limit of the kind of question it asks rather than a defect in it.
A sameness check is blind to a gap shared by every copy, and a deny-list is
only ever as good as the sweep that filled it. Whatever decides what the rule
forbids has to be audited on its own terms; agreement between copies is not
evidence about it.

## Why this is not in SHARED_FILES

That rule demands byte-identical copies, and these cannot be. Each binds the
enumerator its own tree provides, and the keeper's copy also carries the
marker that files it under the architecture tier. Those lines are what makes
a copy work where it sits, and are the only lines allowed to differ.

So this compares everything else, which is where the rule itself lives: the
patterns, the exemptions, the samples and the assertions. A copy may adapt
how it finds files. It may not disagree about what a coordinate is.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from tests._tracked import TREE_ROOT

if TYPE_CHECKING:
    from pathlib import Path

RULE = "test_no_facility_coordinates.py"
"""The file this compares, found wherever a project keeps it."""


def _expected() -> int:
    """One copy per project, plus the checkout's own.

    Derived rather than written down, for the reason the tier enumerator
    gives: a constant and the thing it counts move together, so a sweep that
    lost three copies could be satisfied by editing the number. A project is
    a directory with a `pyproject.toml` of its own, which is what gives it a
    lockfile and a gate, and every one of them has to carry this rule because
    every one of them is published alone.

    So a project added later is required to have a copy without anybody
    remembering, and a project that drops one fails here rather than passing
    quietly with four.
    """
    return 1 + len([d for d in (TREE_ROOT / "apps").iterdir() if (d / "pyproject.toml").is_file()])


_BINDING = re.compile(r"^\s*(from|import)\s+tests[. ]|^pytestmark\s*=")
"""The lines a copy is allowed to differ on.

An import of the enumerator its own tree provides, and the keeper's tier
marker. Both say where the copy sits rather than what it forbids, which is
the whole of the licence to differ.
"""


def _copies() -> dict[str, Path]:
    """Every copy of the rule, keyed by its path from the tree root.

    Walked rather than listed, and not through this tier's enumerator,
    which excludes `apps/` on purpose so that each project scans itself.
    That exclusion is exactly why no existing check could see this drift,
    so the one rule whose job is to compare projects has to look past it.
    Walking also means a project that gains a copy later is covered
    without anybody remembering to add it here.
    """
    skip = {".venv", ".git", "node_modules", "__pycache__", ".claude"}
    return {
        str(path.relative_to(TREE_ROOT)): path
        for path in sorted(TREE_ROOT.rglob(RULE))
        if not skip & set(path.relative_to(TREE_ROOT).parts)
    }


def _substance(path: Path) -> str:
    """The copy with its binding lines removed, which is the rule itself."""
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = (line for line in lines if not _BINDING.match(line))
    return "\n".join(line for line in kept if line.strip())


def test_every_project_and_the_checkout_each_carry_one_copy() -> None:
    found = _copies()
    expected = _expected()
    assert len(found) == expected, (
        f"Found {len(found)} copies of {RULE} in {sorted(found)}, and this "
        f"tree has {expected} places that must carry one: every project, "
        "because each is published alone and runs its own suite, plus the "
        "checkout. A project without a copy is a project this rule does not "
        "reach, and comparing what is left would pass by agreeing with itself."
    )


def test_every_copy_of_the_coordinate_rule_forbids_the_same_things() -> None:
    bodies = {where: _substance(path) for where, path in _copies().items()}
    distinct = set(bodies.values())
    assert len(distinct) == 1, (
        f"{RULE} differs between {sorted(bodies)}, in lines that are not the "
        "import of an enumerator or the keeper's tier marker.\n"
        "These are duplicated rather than shared, so nothing but this check "
        "keeps them in step, and a fix applied to one of five leaves four "
        "projects shipping the old rule with every suite green. Regenerate "
        "the others from whichever copy is right."
    )
