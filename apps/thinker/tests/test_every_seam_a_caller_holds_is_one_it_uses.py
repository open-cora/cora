"""A function handed a seam uses all of it, or passes it along untouched.

`seams` argues at length that a port carrying verbs its caller must never
call is worth splitting, and then one of them carried three where the
loop wanted one. `claim` sat on `Questioning` beside `ask` and
`read_back`, so `intake.serve` held the two verbs for opening a question
and reading one back, and the only thing stopping it from calling them
was that it did not.

The rule was stated in prose and enforced by nobody, which is the shape
this file exists to change. It reads the Protocols out of `seams` and
the calls out of the syntax tree, so neither side is written down twice
and a verb added to a port nobody asks for it from goes red here.

Two ways to hold a seam are allowed, because both appear:

  called into   every verb the Protocol declares is called, so the
                caller wanted the whole of it
  passed along  no verb is called and the parameter is handed to
                something else, which is what `serve` does with the
                three a thinking needs

What is refused is the middle: a caller that reaches for some of a port
and leaves the rest. Holding a seam and neither using nor forwarding it
is refused too, because an argument nothing reads is one somebody meant
to remove.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "thinker"

EXPECTED_HOLDINGS = 12
"""How many seam parameters the scan should find across the package.

Pinned for the reason the sibling structural test pins its counts: a
rename or a move silently shrinks the set a rule ranges over, and a rule
ranging over nothing passes. Raise this only after confirming the scan
sees what you added.
"""


def _protocols() -> dict[str, frozenset[str]]:
    """Each Protocol in `seams`, and the verbs it declares."""
    tree = ast.parse((PACKAGE / "seams.py").read_text(encoding="utf-8"))
    found: dict[str, frozenset[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not any(isinstance(base, ast.Name) and base.id == "Protocol" for base in node.bases):
            continue
        found[node.name] = frozenset(
            member.name
            for member in node.body
            if isinstance(member, ast.FunctionDef) and not member.name.startswith("_")
        )
    return found


def _annotation(node: ast.arg) -> str | None:
    return node.annotation.id if isinstance(node.annotation, ast.Name) else None


def _holdings() -> list[tuple[str, str, str, frozenset[str], bool]]:
    """Every place a function is handed a seam, and what it does with it.

    Each entry is the module, the function, the parameter's Protocol, the
    verbs called on it, and whether the parameter is handed to anything.
    """
    protocols = _protocols()
    held: list[tuple[str, str, str, frozenset[str], bool]] = []

    for path in sorted(PACKAGE.rglob("*.py")):
        if path.parent.name == "adapters":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef):
                continue
            arguments = function.args
            every = arguments.posonlyargs + arguments.args + arguments.kwonlyargs
            for argument in every:
                seam = _annotation(argument)
                if seam is None or seam not in protocols:
                    continue
                held.append(
                    (
                        path.stem,
                        function.name,
                        seam,
                        _called_on(function, argument.arg),
                        _passed_on(function, argument.arg),
                    )
                )
    return held


def _called_on(function: ast.FunctionDef, name: str) -> frozenset[str]:
    return frozenset(
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == name
    )


def _passed_on(function: ast.FunctionDef, name: str) -> bool:
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        given = list(node.args) + [keyword.value for keyword in node.keywords]
        if any(isinstance(value, ast.Name) and value.id == name for value in given):
            return True
    return False


def test_the_scan_finds_every_seam_parameter_this_package_declares() -> None:
    found = _holdings()
    assert len(found) == EXPECTED_HOLDINGS, (
        f"the scan found {len(found)} seam parameters and expects {EXPECTED_HOLDINGS}: "
        f"{[(module, function, seam) for module, function, seam, _, _ in found]}"
    )


@pytest.mark.parametrize("holding", _holdings(), ids=lambda h: f"{h[0]}.{h[1]}({h[2]})")
def test_a_seam_a_function_calls_into_has_every_one_of_its_verbs_called(
    holding: tuple[str, str, str, frozenset[str], bool],
) -> None:
    module, function, seam, called, _ = holding
    if not called:
        return
    declared = _protocols()[seam]
    assert called == declared, (
        f"{module}.{function} is handed {seam} and calls {sorted(called)} of "
        f"{sorted(declared)}. A caller holding a verb it must never call is what "
        f"splitting a port is for."
    )


@pytest.mark.parametrize("holding", _holdings(), ids=lambda h: f"{h[0]}.{h[1]}({h[2]})")
def test_a_seam_a_function_never_calls_is_one_it_hands_to_something_else(
    holding: tuple[str, str, str, frozenset[str], bool],
) -> None:
    module, function, seam, called, passed = holding
    if called:
        return
    assert passed, (
        f"{module}.{function} is handed {seam}, calls nothing on it and gives it to "
        "nobody, so it is an argument that does nothing"
    )
