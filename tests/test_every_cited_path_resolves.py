"""Every repo path this tier cites in prose or source is a file that is there.

`test_every_relative_link_resolves.py` reads one shape, the inline markdown
link, and that is not how this tier's pages cite a file most of the time. A
path arrives in backticks, in a fenced shell command, or in a module
docstring, and none of those is a link. Nothing read them.

That gap has already cost the tree its evidence. `beamlines/EXPANSION.md`
argued three of its decisions from spike findings and cited the files by
path, in backticks. The spikes had never been committed: the citations
pointed at nothing on the day they were written, the suite was green, and
the measurements survived only in a stale worktree. One of the three is
gone for good.

## Why the full path, where the keeper's rule takes a basename

`apps/keeper/tests/architecture/test_docstring_references_resolve.py` asks
only whether a file of that name exists anywhere. That is right there: a
docstring in one project may cite a sibling it cannot see from its own
checkout, so the path cannot be resolved and the basename is what is left.

Here the tree root is the whole subject and a citation resolves against it,
so the stricter question is available and the looser one is actively wrong.
Five spikes carry a `FINDINGS.md`. A basename check passes a citation of
`spikes/access_security/FINDINGS.md`, which is the exact reference this rule
was written after.

## Only paths that start where this tree starts

A spike measures somebody else's software and cites its files while doing
it: `bluesky/callbacks/tiled_writer.py` is a real path in a real package
and none of this tree's business. A rule that demanded it resolve would
force a spike to be edited until its evidence was wrong, which is the
outcome committing the spikes was meant to prevent.

So a citation counts as a citation of this tree when its first segment is a
directory this tree has, and otherwise it is read as naming someone else's.
The set is derived from git rather than spelled out, for the reason
`test_the_tier_enumerates_what_no_project_does.py` gives about constants
that stop matching.

The cost is stated rather than hidden: a path that drops its leading
directory, `reporter/stores.py` for `apps/reporter/src/reporter/stores.py`,
is not checked, because nothing tells it from a path into another tree.
That is the same trade the keeper's rule makes from the other side, where a
basename is all that survives a citation across projects.

## What it does not check

A citation with no `/` in it. `README.md` and `CLAUDE.md` name a file per
directory and resolving them would mean guessing which one was meant, so a
path is a thing with a separator in it and a bare name is a word.

An anchor after the path, for the reason the link rule gives: verifying one
means reimplementing the theme's slugification and going stale quietly.

A URL, which cites somebody else's tree rather than this one.
"""

from __future__ import annotations

import os
import re
import subprocess
from functools import cache
from typing import TYPE_CHECKING

from tests._tracked import (
    TREE_ROOT,
    tracked_prose_files,
    tracked_source_files,
    tracked_test_files,
)

if TYPE_CHECKING:
    from pathlib import Path

_CITED_PATH = re.compile(
    r"([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+\.(?:py|sql|md|toml|yml|yaml|hcl|cff|json))"
)
"""A repo-relative file path, keyed on its extension and its separator.

The extension is what tells a path from a sentence, which is the move the
keeper's rule makes and the reason neither needs to guess. The separator is
what tells it from a bare filename, which this rule declines to resolve.
"""

_SKIPPED = ("http://", "https://", "mailto:", "ftp://")

_THIS_FILE = "test_every_cited_path_resolves.py"
"""The one file excluded, because it has to spell a path that is not there.

The same hole `test_no_phase_markers.py` accepts for the same reason: a file
defining what a broken citation looks like cannot avoid containing one. A
real dead path written into this file goes unseen, which is the narrowest
exemption available.
"""


@cache
def _tree_directories() -> frozenset[str]:
    """Every top-level directory git tracks, `apps/` included.

    Deliberately not routed through `_tracked._ls_files`, which excludes the
    projects. A citation of `apps/keeper/docs/bounded-contexts/execution.md`
    is one this tier should check: the exclusion there is about whose files
    get scanned, not about which paths may be named.
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
    return frozenset(line.split("/", 1)[0] for line in result.stdout.splitlines() if "/" in line)


def _unresolved(
    paths: frozenset[Path], directories: frozenset[str] | None = None
) -> list[tuple[Path, int, str]]:
    """Every cited path in `paths` that is not on disk.

    A citation resolves against the tree root or against the citing file's
    own directory, and either is enough. Both spellings are in use: prose
    at the root cites `beamlines/README.md` from the top, and a spike's
    README names a script beside it.

    `directories` is injected so the planted-defect check below can supply
    its own. Reading the real tree there would make that check depend on
    what happens to be committed.

    Returns the pieces rather than a formatted line, so the check below can
    be shown to fire on a file of its own making. Formatting here would mean
    resolving against the tree root, and a temporary file is not under it.
    """
    known = _tree_directories() if directories is None else directories
    missing: list[tuple[Path, int, str]] = []
    for path in sorted(paths):
        if path.name == _THIS_FILE:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(scheme in line for scheme in _SKIPPED):
                continue
            for cited in _CITED_PATH.findall(line):
                if cited.split("/", 1)[0] not in known:
                    continue
                if (TREE_ROOT / cited).exists() or (path.parent / cited).exists():
                    continue
                missing.append((path, lineno, cited))
    return missing


def _scanned() -> frozenset[Path]:
    return tracked_source_files() | tracked_test_files() | tracked_prose_files()


def test_the_citation_scan_finds_paths_to_check() -> None:
    """Guard the derivation: a regex that stopped matching passes everything."""
    assert _scanned(), "No file scanned."
    found = sum(
        len(_CITED_PATH.findall(path.read_text(encoding="utf-8")))
        for path in _scanned()
        if path.name != _THIS_FILE
    )
    assert found > 20, f"Only {found} cited paths found across this tier, which is too few."


def test_the_scan_catches_a_dead_path_and_leaves_the_other_kinds_alone(tmp_path: Path) -> None:
    """Every arm matters, and the last two are why this rule was rewritten once.

    Missing the first is the defect this file exists for. Firing on a live
    citation makes a rule that gets suppressed rather than obeyed. Firing on
    another project's path would force a spike to be edited until its
    evidence was wrong.
    """
    page = tmp_path / "page.md"
    (tmp_path / "beside.md").write_text("here\n", encoding="utf-8")
    page.write_text(
        "`spikes/nowhere/FINDINGS.md` is gone\n"
        "`tests/_tracked.py` resolves from the tree root\n"
        "`beside.md` is a bare name and not checked\n"
        "`bluesky/callbacks/tiled_writer.py` is another tree's file\n"
        "see https://example.org/a/b/c.md for the upstream\n",
        encoding="utf-8",
    )
    found = _unresolved(frozenset({page}), directories=frozenset({"spikes", "tests"}))
    assert found == [(page, 1, "spikes/nowhere/FINDINGS.md")]


def test_every_cited_path_in_this_tier_resolves() -> None:
    missing = _unresolved(_scanned())
    named = [f"{path.relative_to(TREE_ROOT)}:{lineno}: {cited}" for path, lineno, cited in missing]
    assert not named, (
        "Prose or source cites a file that is not there:\n  "
        + "\n  ".join(named)
        + "\n\nA citation is how a claim is checked. One that points at nothing "
        "makes the claim unverifiable, and the evidence it rested on is usually "
        "what went missing."
    )
