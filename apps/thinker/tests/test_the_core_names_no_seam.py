"""The one structural rule this package has, and a check that it holds.

Thinking is written in `case`, `conclusions`, `seams` and `think`. Between
them those four import the standard library and each other, and nothing
else. What a case is and what a conclusion is therefore do not know that
any particular provider exists, which is what makes changing provider an
adapter rather than a rewrite.

`thinker.adapters` is where knowing is allowed. Each module there speaks to
one outside system, and nothing above imports any of them: an adapter is
named once, at the entrypoint that picks it.

Between the two sits the module that is neither: `config` reads a file. It
composes no case, so it is not core, and it knows no outside system, so it
is not an adapter. It is held to the core's rule anyway, because a loader
that imported an adapter would work perfectly and would be a loader only
one transport could ever use.

None of that is visible in a diff. A single `from thinker.adapters...` in
`think.py` would undo it, would work perfectly, and would make an HTTP
library a hard dependency of forming a conclusion. This is the test. It
reads imports rather than running anything, which is why it is cheap
enough to keep.

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

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "thinker"

CORE = frozenset({"case", "conclusions", "seams", "think"})
"""The modules thinking is written in. Standard library and each other."""

ENTRYPOINT = frozenset({"__init__", "__main__"})
"""The two the rules below treat specially.

`__main__` is the one module allowed to name an adapter, because
something has to. `__init__` gets its own check rather than this one,
because what matters there is narrower: importing this package must not
require any adapter's library.
"""

ADAPTERS_DIR = PACKAGE / "adapters"

EXPECTED_CORE_MODULES = 4
"""How many files `CORE` should find. Moving one without saying so fails here."""

EXPECTED_ADAPTERS = 1
"""Adapter modules under `adapters/`, excluding its `__init__`.

One: the HTTP adapter over the keeper's own API, which is both where a
case is read from and where a proposal is written to.

A provider adapter is the one this number is waiting for. Until then the
sibling check below ranges over a single file and can find nothing, which
is accurate rather than pointless: it is the check that starts mattering
on the day the second adapter lands, and a rule written afterwards is a
rule written after the import it would have caught.
"""

EXPECTED_OUTER_MODULES = 1
"""Root modules that are neither the core nor an entrypoint.

One: `config`, which reads a file. It is held to the core's rule, so this
is pinned for the same reason every other count here is.
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

    `from thinker.adapters.keeper_http import X` yields
    `thinker.adapters.keeper_http` rather than `thinker`, because the
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
        if root.split(".")[0] not in sys.stdlib_module_names and root.split(".")[0] != "thinker"
    )
    assert not outsiders, (
        f"{path.name} imports {outsiders}, so forming a conclusion now needs it "
        "installed. A library belonging to one outside system goes in "
        "thinker/adapters/, behind a Protocol in seams.py."
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
    reached = sorted(
        root
        for root in _imported_roots(path)
        if root.startswith("thinker.adapters")
        or (root.split(".")[0] not in sys.stdlib_module_names and root.split(".")[0] != "thinker")
    )
    assert not reached, (
        f"{path.name} imports {reached}. It sits above thinker/adapters/ and names a "
        "seam by its Protocol, the way the core does; __main__ is where an "
        "implementation is chosen."
    )


@pytest.mark.parametrize("path", _core_paths(), ids=lambda p: p.name)
def test_core_module_imports_no_adapter(path: Path) -> None:
    reached = sorted(root for root in _imported_roots(path) if root.startswith("thinker.adapters"))
    assert not reached, (
        f"{path.name} imports {reached}. The core names a seam by its Protocol "
        "and never by an implementation; the entrypoint chooses which one."
    )


def test_the_package_root_imports_no_adapter() -> None:
    """`import thinker` must not require any outside system's library."""
    reached = sorted(
        root
        for root in _imported_roots(PACKAGE / "__init__.py")
        if root.startswith("thinker.adapters")
    )
    assert not reached, (
        f"thinker/__init__.py imports {reached}, which makes that adapter's "
        "library a hard dependency of importing this package at all."
    )


def test_the_adapters_package_imports_nothing() -> None:
    """Its `__init__` stays empty of imports for the same reason.

    A re-export there would make `import thinker.adapters` pull in every
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
        if root.startswith("thinker.adapters") and not root.endswith(path.stem)
    )
    assert not siblings, f"{path.name} imports sibling adapters {siblings}."
