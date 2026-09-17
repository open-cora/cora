"""No slice imports from a sibling slice in the same bounded context.

Vertical slices are independent units. A handler, decider or route in
`aroc.<bc>.features.<slice_a>` may not import from
`aroc.<bc>.features.<slice_b>`. Shared types belong in the aggregate
kernel under `aroc.<bc>.aggregates`; pure cross-BC value objects belong
in `aroc.shared`; cross-BC machinery with port or kernel dependencies
belongs in `aroc.infrastructure`.

Tach enforces cross-BC rules at module granularity. Expressing the
cross-slice rule there would need one module stanza per slice, so it
lives here as a single AST scan instead.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import AROC_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture


def _slice_python_files() -> list[Path]:
    tracked = tracked_python_files()
    out: list[Path] = []
    for bc in discovered_bcs():
        features = AROC_ROOT / bc / "features"
        out.extend(
            sorted(
                f
                for f in tracked
                if f.parent.parent == features and not f.parent.name.startswith("_")
            )
        )
    return out


def _qualified(p: Path) -> str:
    return "aroc." + ".".join(p.relative_to(AROC_ROOT).with_suffix("").parts)


@pytest.mark.parametrize("py_file", _slice_python_files(), ids=_qualified)
def test_a_slice_file_imports_no_sibling_slice_in_its_own_bc(py_file: Path) -> None:
    qualified = _qualified(py_file)
    parts = qualified.split(".")
    # parts: ["aroc", "<bc>", "features", "<slice>", "<file>"]
    own_bc = parts[1]
    own_slice_prefix = ".".join(parts[:4])
    sibling_features_prefix = f"aroc.{own_bc}.features."

    tree = ast.parse(py_file.read_text())
    violations: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        target = node.module
        if not target.startswith(sibling_features_prefix):
            continue
        if target == own_slice_prefix or target.startswith(own_slice_prefix + "."):
            continue
        violations.append(f"line {node.lineno}: from {target} import ...")

    assert not violations, (
        f"{qualified} imports from a sibling slice in the same bounded context:\n  "
        + "\n  ".join(violations)
        + "\nMove the shared type into the aggregate kernel, aroc.shared, "
        "or aroc.infrastructure."
    )
