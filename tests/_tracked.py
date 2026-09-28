"""Git's view of the tree, minus the projects that check themselves.

Every check here enumerates through git rather than walking the filesystem,
for the reason each project's own helper gives: pre-commit stashes unstaged
changes to tracked files and never untracked ones, so during a hook run a
half-written file sits live on disk. A walk sees that arrangement and fails
on it; git's tracked set sees what pre-commit is evaluating.

The corollary is the trap, and a green run looks the same either way: a file
git has never seen is invisible to every check below. Stage new files before
trusting one.

## What this tier owns

Everything outside `apps/`. Each project under there carries its own copy of
these rules and scans itself, because it is published as a repository of its
own and has to run its suite with nothing beside it. Scanning them from here
too would double-report every hit and, worse, would let a project's own copy
rot unnoticed behind this one.

What that leaves is the part no project owns and nothing was checking: the
root prose, the CORA site, and `beamlines/`, which describes a facility rather
than a system and belongs to none of them. Three passes of prose fixes during
the restructure missed that directory every time, because no rule reached it.
"""

from __future__ import annotations

import os
import subprocess
from functools import cache
from pathlib import Path

TREE_ROOT = Path(__file__).resolve().parents[1]
"""The directory holding the root `pyproject.toml`, which is the checkout."""

APPS_DIR = "apps"
"""The one directory excluded, because everything in it checks itself.

Named once here rather than spelled into each pathspec below, and a test
asserts the exclusion still removes something. A filter that has stopped
matching is indistinguishable from a clean tree, which is the failure this
tree has already had once, in a lint hook whose pattern named a directory
that had been renamed.
"""


def _ls_files(*pathspecs: str) -> list[str]:
    """Tracked paths outside `apps/`, relative to the checkout.

    GIT_DIR and GIT_INDEX_FILE are stripped because pre-commit points them at
    its own staging area. Left in place inside a worktree they name the parent
    checkout's index, and the answer is then the wrong repository's files.
    """
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_DIR", "GIT_INDEX_FILE"}}
    result = subprocess.run(
        ["git", "ls-files", "--", *(pathspecs or (".",)), f":(exclude){APPS_DIR}"],
        cwd=TREE_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return result.stdout.splitlines()


@cache
def tracked_source_files() -> frozenset[Path]:
    """Absolute paths to tracked `.py` files this tier owns, tests aside.

    Two directories, and they are unalike on purpose. `beamlines/` is
    maintained: prose and scripts describing a facility, expected to track
    the tree. `spikes/` is dated evidence, programs written to settle one
    question and kept because prose that outlived them cites the answers.

    Both are scanned by the same rules. A spike is exempt from being
    current, never from being readable, and the alternative is a directory
    of committed source that no rule in this tree reaches.
    """
    return frozenset(
        TREE_ROOT / line
        for line in _ls_files("beamlines", "spikes")
        if line.endswith(".py") and "/tests/" not in line
    )


@cache
def tracked_test_files() -> frozenset[Path]:
    """Absolute paths to tracked `.py` files in either of the two test roots."""
    return frozenset(
        TREE_ROOT / line for line in _ls_files("tests", "beamlines/tests") if line.endswith(".py")
    )


@cache
def tracked_prose_files() -> frozenset[Path]:
    """Absolute paths to every tracked `.md` file this tier owns.

    The root pages, the CORA site and the beamline prose. Not the projects',
    which their own suites read.
    """
    return frozenset(TREE_ROOT / line for line in _ls_files() if line.endswith(".md"))
