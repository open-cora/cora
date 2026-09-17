"""Every slice directory names a subject, not just a verb.

Slice directories follow `<verb>_<subject>[_<qualifier>]`. The subject
names what the slice acts on. A bare verb tells a reader that something
happens without saying to what, and a directory named that way is almost
always a slice that belongs somewhere other than a bounded context's
features/ folder.

The set of recognised subjects is DERIVED from the tree: every aggregate
folder under any bounded context, plus its regular plural forms for the
list-style query slices. Nothing is hand-listed, so a new aggregate is
recognised the moment it exists rather than when someone remembers to
extend a tuple.

That derivation is the check's independent side. A slice name and an
aggregate folder name are written in two different places by two
different acts, so agreement between them is evidence. The rule catches
a slice naming a subject the codebase does not have, which is what a
typo and a bare verb both look like.

`_DOMAIN_NOUN_ALLOWLIST` is for a subject that is a persisted value type
rather than an aggregate, so no folder exists to derive it from. It is
empty. An entry belongs in docs/reference/conventions.md as well, since
it widens the vocabulary the rule accepts.
"""

from functools import cache
from pathlib import Path

import pytest

from tests.architecture.conftest import AROC_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture

_DOMAIN_NOUN_ALLOWLIST: frozenset[str] = frozenset()
"""Subjects that name a persisted value type rather than an aggregate.

Empty. Add an entry only when the subject is real and has no aggregate
folder to be derived from, and document it alongside the other naming
rules so the vocabulary stays written down in one place.
"""


@cache
def _aggregate_names() -> frozenset[str]:
    """Aggregate folder names across every bounded context, from tracked files.

    Derived from git-tracked paths rather than a directory walk, so an
    untracked work-in-progress aggregate is invisible here in the same way
    it is invisible to pre-commit.
    """
    names: set[str] = set()
    for path in tracked_python_files():
        parts = path.parts
        for index, part in enumerate(parts):
            if part == "aggregates" and index + 1 < len(parts) - 1:
                names.add(parts[index + 1])
    return frozenset(names)


@cache
def _known_subjects() -> frozenset[str]:
    return _aggregate_names() | _DOMAIN_NOUN_ALLOWLIST


def _plural_to_singular(token: str) -> str:
    """Map the regular English plural forms back to the singular."""
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ches") or token.endswith("shes"):
        return token[:-2]
    if token.endswith("s") and len(token) > 1 and not token.endswith("ss"):
        return token[:-1]
    return token


@cache
def _slice_dirs() -> list[Path]:
    """Every tracked slice directory under any bounded context's features/."""
    dirs: set[Path] = set()
    for bc in discovered_bcs():
        features = AROC_ROOT / bc / "features"
        for path in tracked_python_files():
            if path.parent.parent != features:
                continue
            if path.parent.name.startswith("_"):
                continue
            dirs.add(path.parent)
    return sorted(dirs)


def _slice_id(p: Path) -> str:
    return p.parent.parent.name + "." + p.name


@pytest.mark.parametrize("slice_dir", _slice_dirs(), ids=_slice_id)
def test_a_slice_directory_name_carries_a_known_subject(slice_dir: Path) -> None:
    bc = slice_dir.parent.parent.name
    qualified = f"aroc.{bc}.features.{slice_dir.name}"
    known = _known_subjects()
    tokens = slice_dir.name.split("_")
    if any(_plural_to_singular(token) in known or token in known for token in tokens):
        return
    pytest.fail(
        f"{qualified} names no recognised subject.\n"
        f"  tokens:            {tokens}\n"
        f"  known aggregates:  {sorted(_aggregate_names())}\n"
        f"  allowlisted nouns: {sorted(_DOMAIN_NOUN_ALLOWLIST)}\n\n"
        "A slice directory is <verb>_<subject>[_<qualifier>]. The subject names "
        "the aggregate the slice acts on, not just the verb's grammatical object. "
        "If the subject is a persisted value type with no aggregate of its own, "
        "add it to _DOMAIN_NOUN_ALLOWLIST here and to the naming rules in "
        "docs/reference/conventions.md. Otherwise carry the subject into the "
        "slice, command and tool names together."
    )
