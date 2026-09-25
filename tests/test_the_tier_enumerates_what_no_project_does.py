"""Guard the enumeration this tier is built on.

Every rule here ranges over what `_tracked.py` returns, so an enumerator that
stopped matching would leave each of them passing on an empty set. That is the
failure this tree has already had: a lint hook whose file pattern named a
directory that had been renamed matched none of one project's 538 files and
reported success on every commit for weeks.

## Why the projects are derived rather than read from the helper

The first version of this file asked `_tracked.APPS_DIR` which directory was
excluded and then asserted that nothing under it was enumerated. That reads
like a check and is not one: both sides move together, so setting the constant
to a directory that is not the projects satisfies the assertion built from it.
Changing it to `docs` let all four projects into the scan and every test here
still passed.

So a project is derived from the tree instead: a directory with a
`pyproject.toml` of its own is a thing with its own lockfile and its own gate,
which is what makes it a project and what makes its files someone else's to
check. That fact survives a rename; a constant does not.
"""

from __future__ import annotations

import os
import subprocess
from functools import cache

from tests._tracked import (
    APPS_DIR,
    TREE_ROOT,
    tracked_prose_files,
    tracked_source_files,
    tracked_test_files,
)


def _every_tracked_file() -> list[str]:
    """Every tracked path in the checkout, exclusion and all.

    Deliberately not routed through `_ls_files`, because what is being checked
    is what that helper leaves out. Asking it would be asking the subject of
    the test to report on itself.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_INDEX_FILE"}}
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=TREE_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.splitlines()


@cache
def _project_directories() -> tuple[str, ...]:
    """Every directory holding a `pyproject.toml` of its own, the tree aside."""
    return tuple(
        sorted(
            line.rsplit("/", 1)[0]
            for line in _every_tracked_file()
            if line.endswith("pyproject.toml") and "/" in line
        )
    )


def test_the_tree_still_holds_projects_to_exclude() -> None:
    """Guard the derivation itself: an empty list makes both checks vacuous."""
    assert _project_directories(), (
        "No directory under this one carries a pyproject.toml, so the two "
        "checks below range over nothing and pass on any exclusion at all."
    )


def test_every_enumerator_finds_something() -> None:
    """Named one at a time, so a failure says which pathspec stopped matching."""
    assert tracked_source_files(), "No source file found outside the projects."
    assert tracked_test_files(), "No test file found in either test root."
    assert tracked_prose_files(), "No prose file found outside the projects."


def test_the_excluded_directory_covers_every_project() -> None:
    """The one exclusion has to reach all of them, whatever they are called."""
    uncovered = [p for p in _project_directories() if not p.startswith(f"{APPS_DIR}/")]
    assert not uncovered, (
        f"These are projects and the exclusion does not reach them: {uncovered}. "
        f"This tier excludes {APPS_DIR}/ and nothing else, so a project outside "
        "it is scanned twice: once by its own suite and once by this one."
    )


def test_no_enumerated_file_belongs_to_a_project() -> None:
    """The result of the exclusion, checked against what a project really is."""
    projects = _project_directories()
    enumerated = tracked_source_files() | tracked_test_files() | tracked_prose_files()
    intruders = sorted(
        relative
        for path in enumerated
        for relative in (path.relative_to(TREE_ROOT).as_posix(),)
        if any(relative.startswith(f"{project}/") for project in projects)
    )
    assert not intruders, (
        f"This tier is reading files that belong to a project: {intruders}. Each "
        "one carries its own copy of these rules and scans itself, so a hit here "
        "would be reported twice and that project's own copy could rot behind "
        "this one."
    )
