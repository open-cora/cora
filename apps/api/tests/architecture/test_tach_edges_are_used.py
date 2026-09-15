"""Every `depends_on` edge in tach.toml is taken up by a real import.

tach enforces that nothing imports what it may not. It says nothing about the
reverse: a permission granted for a reason that has since gone away stays in
the file forever, and the contract slowly stops describing the system.

The asymmetry matters because the two errors have different costs. A missing
edge fails loudly the moment someone adds the import. A stale edge fails
never, and quietly widens what the next author is allowed to do.

## What this cannot see

tach constrains IMPORTS, and an import is only one of the ways one module
comes to depend on another. A Protocol declared in `infrastructure.ports`,
implemented by one BC and consumed by another, creates a real dependency that
leaves no import to constrain: both sides name only `aroc.infrastructure`.
So a green run here means the declared edges are all used, NOT that the
declared edges are all the dependencies.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from tests.architecture.conftest import tracked_python_files

pytestmark = pytest.mark.architecture

TACH_TOML = "tach.toml"


def _modules() -> list[dict[str, Any]]:
    from tests.architecture.conftest import SRC_ROOT

    path = SRC_ROOT.parent / TACH_TOML
    modules: list[dict[str, Any]] = tomllib.loads(path.read_text())["modules"]
    return modules


def test_tach_declares_at_least_one_module() -> None:
    """Guard the enumeration, so the check below cannot pass vacuously."""
    assert _modules(), "tach.toml declares no modules; the check below examines nothing."


def test_every_declared_dependency_edge_is_taken_up_by_an_import() -> None:
    modules = _modules()
    sources = {p: p.read_text() for p in tracked_python_files()}

    unused: list[str] = []
    for module in modules:
        owner = str(module["path"])
        owner_prefix = owner + "."
        for target in module.get("depends_on", []) or []:
            target = str(target)
            # An import of the target from anywhere inside the owning module.
            pattern = re.compile(
                rf"^\s*(?:from\s+{re.escape(target)}[\s.]|import\s+{re.escape(target)}\b)",
                re.MULTILINE,
            )
            taken_up = any(
                pattern.search(text)
                for path, text in sources.items()
                if _module_of(path) == owner or _module_of(path).startswith(owner_prefix)
            )
            if not taken_up:
                unused.append(f"{owner} -> {target}")

    assert not unused, (
        "tach.toml grants dependency edges no source file takes up:\n"
        + "\n".join(f"  {u}" for u in unused)
        + "\nRemove the edge, or add the import that justified it. A permission "
        "whose reason has gone away should not quietly stay."
    )


def _module_of(path: Path) -> str:
    """Map a source path to the dotted module prefix tach would attribute it to."""
    from tests.architecture.conftest import SRC_ROOT

    rel = str(path).removeprefix(str(SRC_ROOT) + "/").removesuffix(".py")
    return rel.replace("/__init__", "").replace("/", ".")
