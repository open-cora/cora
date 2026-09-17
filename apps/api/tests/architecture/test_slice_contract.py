"""Every vertical slice carries its required modules.

Two slice shapes:

    command slice   __init__, command, decider, handler, route, tool
    query slice     __init__, query,            handler, route, tool

A query has no decider because reading decides nothing. A slice is one
or the other and never both: a directory declaring a command module and
a query module together has two intents fused, and the reader cannot
tell which one the route serves.

A directory under a features/ folder with neither a command nor a query
module is treated as a stub that is not yet wired and is skipped. The
moment either appears, the rest of the contract becomes mandatory.

`WIP_SLICES` is the escape hatch for a slice deliberately landed across
several commits. It is empty. An entry costs a reason and is pruned by
the drift check below once the slice completes.

Deliberately absent, compared with the codebase this check came from:
that one carries two further allowlists for command-shaped slices that
have no decider, because a handler writes to a typed side table or
delegates to an orchestration runtime. This repository has neither, so
it has no allowlist for them, and its rule is the stricter one: every
command slice has a decider. A slice shape that genuinely needs no
decider changes this file as part of the change that introduces it.
"""

from collections.abc import Iterable
from pathlib import Path

import pytest

from tests.architecture.conftest import AROC_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture

_COMMAND_SLICE_MODULES: frozenset[str] = frozenset(
    {"__init__.py", "command.py", "decider.py", "handler.py", "route.py", "tool.py"}
)
_QUERY_SLICE_MODULES: frozenset[str] = frozenset(
    {"__init__.py", "query.py", "handler.py", "route.py", "tool.py"}
)

WIP_SLICES: frozenset[str] = frozenset()
"""Slices mid-flight across commits, by qualified directory name.

Empty. An entry must say what completes it. The drift check below fails
on an entry naming a directory that no longer exists, so a finished slice
cannot leave its exemption behind.
"""


def _qualified(slice_dir: Path) -> str:
    rel = slice_dir.relative_to(AROC_ROOT)
    return "aroc." + ".".join(rel.parts)


def _all_slices() -> list[Path]:
    tracked = tracked_python_files()
    dirs: set[Path] = set()
    for bc in discovered_bcs():
        features = AROC_ROOT / bc / "features"
        for f in tracked:
            if f.parent.parent != features:
                continue
            slice_dir = f.parent
            if slice_dir.name.startswith("_"):
                continue
            dirs.add(slice_dir)
    return sorted(dirs)


def test_the_slice_directory_scan_finds_at_least_one_slice() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _all_slices(), (
        "No slice directory found under any bounded context's features/ "
        "directory, so the contract below ran against nothing."
    )


@pytest.mark.parametrize("slice_dir", _all_slices(), ids=_qualified)
def test_a_slice_declares_every_module_its_shape_requires(slice_dir: Path) -> None:
    qualified = _qualified(slice_dir)
    if qualified in WIP_SLICES:
        pytest.skip(f"{qualified} is allowlisted in WIP_SLICES")

    files = {p.name for p in tracked_python_files() if p.parent == slice_dir}
    has_command = "command.py" in files
    has_query = "query.py" in files

    if not has_command and not has_query:
        pytest.skip(f"{qualified} is a stub: it declares neither a command nor a query")

    assert not (has_command and has_query), (
        f"{qualified} declares both a command and a query module. A slice is one "
        "intent: either it decides and writes, or it reads. Split it."
    )

    required = _COMMAND_SLICE_MODULES if has_command else _QUERY_SLICE_MODULES
    missing = required - files
    assert not missing, f"{qualified} is missing {sorted(missing)}"


def _stale_slice_entries(allowlist: Iterable[str], root: Path) -> list[str]:
    """Allowlist keys naming a slice directory that is not there, with the reason.

    Takes the source root as an argument so the check can be run against
    a tree built for the purpose. `WIP_SLICES` is empty, so otherwise
    neither the prefix check nor the path join would ever execute.
    """
    stale: list[str] = []
    for qualified in sorted(allowlist):
        parts = qualified.split(".")
        if parts[0] != "aroc":
            stale.append(f"{qualified}: must start with 'aroc.'")
        elif not root.joinpath(*parts[1:]).is_dir():
            stale.append(f"{qualified}: names a slice directory that no longer exists.")
    return stale


def test_no_allowlisted_slice_has_gone_missing_from_disk() -> None:
    """Drift catcher: an entry naming a deleted or renamed slice is dead weight."""
    stale = _stale_slice_entries(WIP_SLICES, AROC_ROOT)
    assert not stale, "WIP_SLICES entries to prune:\n  " + "\n  ".join(stale)


def test_the_drift_catcher_reports_an_entry_that_names_no_slice() -> None:
    """Run the catcher over stale entries, because the allowlist is empty.

    A live slice must pass, or the check would reject every entry and
    the allowlist would be unusable the first time somebody needed it.
    """
    assert _stale_slice_entries(["aroc.access.features.register_actor"], AROC_ROOT) == []

    assert _stale_slice_entries(["elsewhere.features.thing"], AROC_ROOT) == [
        "elsewhere.features.thing: must start with 'aroc.'"
    ]

    (gone,) = _stale_slice_entries(["aroc.access.features.vanished"], AROC_ROOT)
    assert "no longer exists" in gone
