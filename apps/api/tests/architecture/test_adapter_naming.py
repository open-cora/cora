"""Adapter classes are `<Tech><Port>`, with no `Adapter` suffix.

`PostgresEventStore`, `JwtTokenVerifier`, `InMemoryIdempotencyStore`. The port
name is the tail, so an adapter sorts next to its siblings and reads as "the
Postgres one of these" rather than as a separate noun.

The suffix is banned because it carries no information: every class in this
directory is an adapter, so saying so distinguishes nothing while making every
name four characters longer.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import ast

import pytest

from tests.architecture.conftest import AROC_ROOT

pytestmark = pytest.mark.architecture

ADAPTERS_DIR = AROC_ROOT / "infrastructure" / "adapters"

ALLOWED_NON_ADAPTER_SUFFIXES = ("Registry", "Error")
"""Classes in the adapters package that are not themselves adapters.

A version-dispatch registry holds adapters rather than being one, and an error
class raised by an adapter belongs beside it. Both are named for what they
are; neither should be forced into the `<Tech><Port>` shape.
"""


def test_adapters_directory_is_not_empty() -> None:
    """Guard the enumeration, so the check below cannot pass vacuously."""
    modules = [p for p in ADAPTERS_DIR.glob("*.py") if p.name != "__init__.py"]
    assert modules, "No adapter modules found; the check below examines nothing."


def test_no_adapter_class_carries_an_adapter_suffix() -> None:
    offenders: list[str] = []
    for path in sorted(ADAPTERS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
                continue
            if node.name.endswith("Adapter"):
                offenders.append(f"{path.name}:{node.name}")
    assert not offenders, (
        "Adapter classes carrying a redundant `Adapter` suffix: "
        f"{offenders}. Name them `<Tech><Port>`."
    )


def test_adapter_module_filenames_are_snake_case_of_their_class() -> None:
    """A filename that does not match its class is a grep that fails."""
    offenders: list[str] = []
    for path in sorted(ADAPTERS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text())
        classes = [
            n.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef)
            and not n.name.startswith("_")
            and not n.name.endswith(ALLOWED_NON_ADAPTER_SUFFIXES)
        ]
        if not classes:
            continue
        stem = path.stem.replace("_", "")
        if not any(cls.lower() == stem for cls in classes):
            offenders.append(f"{path.name} defines {classes}")
    assert not offenders, "Adapter filenames not matching snake_case of their class:\n" + "\n".join(
        offenders
    )
