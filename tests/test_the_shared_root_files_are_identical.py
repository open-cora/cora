"""Files every project carries a copy of must be the same copy.

Four files are duplicated rather than shared, because repositories that
build and ship separately cannot import one another and each has to hold
its own licence, its own Python pin and its own scanning workflow.
Duplication is the right answer and drift is what makes it the wrong one.

## Where this lives, and why it moved

In the tree's own test tier. It sat in the keeper's architecture tier
first, for no better reason than that the keeper was the only project with
one, and it was the single rule left there that reached outside its own
project. That showed up the moment the keeper was checked as a repository
of its own: a fresh clone of its published prefix failed nine of these,
all because the siblings they compare against are not in it.

A rule comparing four repositories belongs to none of them.

## Why this check outlives the split after all

An earlier version of this docstring said the opposite: that the rule
could only work while the trees shared a checkout, and should be deleted
once each project became a repository of its own. That was written when
the plan was four independent repositories.

The plan changed. This tree stays one tree and publishes each project as a
mirror, so the copies never stop sharing a checkout and this rule never
stops having something to compare. It is the reason the duplication is
tolerable: four copies that a test proves identical are a different thing
from four copies that merely started out that way.

## What is deliberately not here

`CLAUDE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `CITATION.cff`, the
`Makefile`, the pre-commit config and the CI workflow. Every one of those
exists in all four and every one says something different in each,
because each describes its own tree. Comparing them would be comparing
four answers to four questions.
"""

from pathlib import Path

import pytest

from tests._tracked import TREE_ROOT

SHARED_FILES: tuple[str, ...] = (
    "LICENSE",
    ".python-version",
    ".gitignore",
    ".github/workflows/codeql.yml",
)
"""Paths each project carries a byte-identical copy of.

An entry earns its place by saying nothing about the project it sits in.
The licence is the same grant, the Python pin is the same interpreter, the
ignore rules name the same tooling, and the scanning workflow runs the
same analysis. A file that would need one word changed per project does
not belong here; it belongs in the list the module docstring refuses.
"""

PROJECTS: tuple[tuple[str, str], ...] = (
    ("cora", "."),
    ("keeper", "apps/keeper"),
    ("conductor", "apps/conductor"),
    ("reporter", "apps/reporter"),
)
"""Each repository published from this tree, and its root directory.

Four, not three. The checkout itself is one of them: it is published as
the development tree, so it carries the same licence and the same pin as
the projects inside it and is as able to drift from them.

It was labelled by position while this rule lived in the keeper, whose
source may not name the sibling project the chassis came from and which
shares this tree's name. Out here that rule does not reach, and the four
entries can each be called what they are.

The keeper's entry used to be the checkout, back when the root files were
the keeper's files and it had no directory of its own to put them in. It
has one now, so the two are separate entries and each is checked against
the rest.

Written out per project rather than probed for. An earlier version looked
for a project's own copy and fell back to the root when it found none,
which made the keeper's case work and made a client that had LOST its copy
indistinguishable from one that never needed it. Deleting the reporter's
licence passed.
"""


def _copy_path(base: str, relative: str) -> Path:
    """Where the project rooted at `base` keeps its copy of `relative`."""
    return TREE_ROOT / base / relative


def test_every_project_directory_exists() -> None:
    """Guard the enumeration: a renamed project silently drops out.

    Without this, a typo in `PROJECTS` would compare two copies instead of
    three and report green on the pair that happened to agree.
    """
    missing = [base for _, base in PROJECTS if not (TREE_ROOT / base).is_dir()]
    assert not missing, f"Listed projects that are not directories: {missing}"


@pytest.mark.parametrize("relative", SHARED_FILES)
def test_a_shared_file_is_present_in_every_project(relative: str) -> None:
    """A project missing its copy would ship without the file entirely.

    Checked before the contents are compared, because a missing file and a
    changed one need different fixes and `read_text` would raise for the
    first while naming neither.
    """
    absent = [name for name, base in PROJECTS if not _copy_path(base, relative).is_file()]
    assert not absent, (
        f"{relative} is missing from {absent}. Each project becomes a "
        "repository of its own, and a repository without this file ships "
        "without it."
    )


@pytest.mark.parametrize("relative", SHARED_FILES)
def test_every_copy_of_a_shared_file_is_byte_identical(relative: str) -> None:
    contents = {name: _copy_path(base, relative).read_bytes() for name, base in PROJECTS}
    distinct = set(contents.values())
    assert len(distinct) == 1, (
        f"{relative} differs between projects: "
        f"{ {p: len(v) for p, v in contents.items()} }.\n"
        "These are duplicated rather than shared, so nothing but this check "
        "keeps them in step. Either copy the intended version across, or, if "
        "this file now has to say something different per project, drop it "
        "from SHARED_FILES and say why in the module docstring."
    )
