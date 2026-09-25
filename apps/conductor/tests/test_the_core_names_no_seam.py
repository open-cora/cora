"""The one structural rule this package has, and a check that it holds.

A procedure is written in `claims`, `procedure`, `seams`, `conduct` and
`outcomes`. Between them those five import the standard library and each
other, and nothing else. The vocabulary a beamline routine is composed in
therefore does not know that Channel Access exists, which is what makes a
Tango deployment an adapter rather than a rewrite.

`conductor.adapters` is where knowing is allowed. Each module there speaks
to one outside system, and nothing above imports any of them: an adapter is
named once, at the entrypoint that picks it. Whether it needs that system's
library to do so varies, and is not what these checks are about.

Between the two sit the modules that are neither: `config` reads a file and
`intake` drives the seams round a loop. Neither composes a procedure, so
neither is core, and neither knows an outside system, so neither is an
adapter. They are held to the core's rule anyway. A loop that imported the
HTTP adapter would work perfectly and would be a loop only one transport
could ever use, which is the whole arrangement undone by one import in the
one module written to survive it.

None of that is visible in a diff. A single `from conductor.adapters...` in
`conduct.py` would undo it, would work perfectly, and would make pyepics a
hard dependency of composing a procedure. The reporter next door had the
same split broken quietly once, by a helper filed on the wrong side, and no
test failed because there was no test. This is that test. It reads imports
rather than running anything, which is why it is cheap enough to keep.

## Why the counts are pinned

Every check below ranges over a set discovered from disk. A rename, a move
or a typo silently shrinks that set, and a rule ranging over nothing passes.
The pins turn "found nothing to check" into a failure. Raise one only after
confirming the rule now sees what you added, never to make a red run green.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "conductor"

CORE = frozenset({"claims", "procedure", "seams", "outcomes", "conduct"})
"""The modules a procedure is composed in. Standard library and each other."""

ENTRYPOINT = frozenset({"__init__", "__main__"})
"""The two the rules below treat specially.

`__main__` is the one module allowed to name an adapter, because
something has to. `__init__` gets its own check rather than this one,
because what matters there is narrower: importing this package must not
require any adapter's library.
"""

ADAPTERS_DIR = PACKAGE / "adapters"

EXPECTED_CORE_MODULES = 5
"""How many files `CORE` should find. Moving one without saying so fails here."""

EXPECTED_ADAPTERS = 3
"""Adapter modules under `adapters/`, excluding its `__init__`.

Three: the Channel Access control seam, the RunEngine acquisition seam,
and the HTTP one over the keeper's own API. The checks below were confirmed to
range over each when it arrived, which is what raising this number is
supposed to mean.

The third is the one that makes `test_the_package_root_imports_no_adapter`
worth more than it was. The keeper is the system every part of this talks to,
so an import of it from the package root would look ordinary and would
still be the rule broken.
"""


EXPECTED_OUTER_MODULES = 2
"""Root modules that are neither the core nor an entrypoint.

Two: `config`, which reads a file, and `intake`, which drives the seams
round a loop. Both are held to the core's rule, so this is pinned for the
same reason every other count here is.
"""


def _core_paths() -> list[Path]:
    return sorted(PACKAGE / f"{name}.py" for name in CORE)


def _outer_paths() -> list[Path]:
    """Everything at the package root that is neither core nor an entrypoint."""
    return sorted(
        path
        for path in PACKAGE.glob("*.py")
        if path.stem not in CORE and path.stem not in ENTRYPOINT
    )


def _adapter_paths() -> list[Path]:
    return sorted(p for p in ADAPTERS_DIR.glob("*.py") if p.name != "__init__.py")


def _imported_roots(path: Path) -> set[str]:
    """Top-level package name of every import in a module.

    `from conductor.adapters.epics_control import X` yields
    `conductor.adapters.epics_control` rather than `conductor`, because the
    checks below need to tell a core-to-core import from a core-to-adapter
    one, and the root alone cannot.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module)
    return roots


def test_every_core_module_is_on_disk() -> None:
    """Guard the enumeration, so the checks below cannot pass vacuously."""
    missing = [p.name for p in _core_paths() if not p.exists()]
    assert not missing, f"CORE names modules that are not there: {missing}"
    assert len(_core_paths()) == EXPECTED_CORE_MODULES


def test_at_least_one_adapter_is_on_disk() -> None:
    """The same guard for the other side of the rule."""
    found = _adapter_paths()
    assert found, "No adapter module found, so the adapter checks examine nothing."
    assert len(found) == EXPECTED_ADAPTERS, f"Adapter count moved: {[p.name for p in found]}"


@pytest.mark.parametrize("path", _core_paths(), ids=lambda p: p.name)
def test_core_module_imports_nothing_outside_the_standard_library(path: Path) -> None:
    outsiders = sorted(
        root
        for root in _imported_roots(path)
        if root.split(".")[0] not in sys.stdlib_module_names and root.split(".")[0] != "conductor"
    )
    assert not outsiders, (
        f"{path.name} imports {outsiders}, so composing a procedure now needs it "
        "installed. A library belonging to one outside system goes in "
        "conductor/adapters/, behind a Protocol in seams.py."
    )


def test_every_module_outside_the_core_is_accounted_for() -> None:
    """The same guard, for the modules that belong to neither side."""
    found = _outer_paths()
    assert len(found) == EXPECTED_OUTER_MODULES, (
        f"Root modules outside the core moved: {[p.name for p in found]}. Each one is "
        "held to the core's rule, so a new one is a deliberate addition rather than a "
        "number to raise."
    )


@pytest.mark.parametrize("path", _outer_paths(), ids=lambda p: p.name)
def test_a_module_outside_the_core_is_held_to_the_core_rule(path: Path) -> None:
    """Neither an adapter nor anybody else's library.

    `intake` is the one this exists for. It drives three seams and knows
    none of them, and an import of the HTTP one would still pass every
    other test in this tree.
    """
    reached = sorted(
        root
        for root in _imported_roots(path)
        if root.startswith("conductor.adapters")
        or (root.split(".")[0] not in sys.stdlib_module_names and root.split(".")[0] != "conductor")
    )
    assert not reached, (
        f"{path.name} imports {reached}. It sits above conductor/adapters/ and names a "
        "seam by its Protocol, the way the core does; __main__ is where an "
        "implementation is chosen."
    )


@pytest.mark.parametrize("path", _core_paths(), ids=lambda p: p.name)
def test_core_module_imports_no_adapter(path: Path) -> None:
    reached = sorted(
        root for root in _imported_roots(path) if root.startswith("conductor.adapters")
    )
    assert not reached, (
        f"{path.name} imports {reached}. The core names a seam by its Protocol "
        "and never by an implementation; the entrypoint chooses which one."
    )


def test_the_package_root_imports_no_adapter() -> None:
    """`import conductor` must not require any outside system's library."""
    reached = sorted(
        root
        for root in _imported_roots(PACKAGE / "__init__.py")
        if root.startswith("conductor.adapters")
    )
    assert not reached, (
        f"conductor/__init__.py imports {reached}, which makes that adapter's "
        "library a hard dependency of importing this package at all."
    )


def test_the_adapters_package_imports_nothing() -> None:
    """Its `__init__` stays empty of imports for the same reason.

    A re-export there would make `import conductor.adapters` pull in every
    adapter's library, which is the hard dependency this rule exists to
    avoid, reintroduced one level down.
    """
    assert not _imported_roots(ADAPTERS_DIR / "__init__.py")


@pytest.mark.parametrize("path", _adapter_paths(), ids=lambda p: p.name)
def test_adapter_imports_the_core_only_through_its_public_names(path: Path) -> None:
    """An adapter may use the core. It may not reach into another adapter.

    Two adapters that shared code would be two outside systems joined
    through this package, and whichever one imported the other would drag
    its library along.
    """
    siblings = sorted(
        root
        for root in _imported_roots(path)
        if root.startswith("conductor.adapters") and not root.endswith(path.stem)
    )
    assert not siblings, f"{path.name} imports sibling adapters {siblings}."
