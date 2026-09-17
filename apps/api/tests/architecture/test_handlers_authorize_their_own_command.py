"""Every handler authorizes under the command name it declares.

A handler names its command once, as `_COMMAND_NAME`, and uses that
string in three places: the authorization call, the event envelope, and
its log lines. Only the first of them decides anything.

Slices are written by copying the nearest one, which is how a new
handler ends up authorizing under its neighbour's name. Nothing about
that is visible. The slice works, its tests pass, its events carry the
right label, and the gate it runs is the wrong gate: a principal
permitted to grant could revoke, or a read could be admitted by a
permission somebody was given for something else.

`AllowAllAuthorize` is what makes this silent. It answers the same way
whatever it is handed, and it is the adapter every test below the
contract tier runs against, so no behavioural test in this repository
can see the argument at all.

## What is checked

In each handler module: find the call to `.authorize(...)` and require
its `command_name` argument to be the bare name `_COMMAND_NAME`. A
literal string is refused even when it is the right string, because the
whole point of the constant is that the slice says its name once.

Read from the source rather than by importing, for the same reason as
the rest of this directory: a fact that holds because an import happened
to succeed is weaker than one written down.
"""

import ast
from pathlib import Path

import pytest

from tests.architecture.conftest import AROC_ROOT, discovered_bcs, tracked_python_files

pytestmark = pytest.mark.architecture


def _handler_modules() -> list[Path]:
    """Every slice handler under a bounded context's features/ directory."""
    return sorted(
        path
        for path in tracked_python_files()
        if path.name == "handler.py"
        and path.parent.parent.name == "features"
        and path.parent.parent.parent.name in discovered_bcs()
    )


def _slice_id(path: Path) -> str:
    rel = path.relative_to(AROC_ROOT)
    return f"{rel.parts[0]}/{path.parent.name}"


def _authorize_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "authorize"
    ]


def test_the_handler_scan_finds_a_handler_in_every_bounded_context() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    found = _handler_modules()
    contexts = {p.relative_to(AROC_ROOT).parts[0] for p in found}
    assert contexts == set(discovered_bcs()), (
        f"handlers found in {sorted(contexts)}, bounded contexts are "
        f"{sorted(discovered_bcs())}. The rule below would range over only part "
        "of the tree."
    )


@pytest.mark.parametrize("handler", _handler_modules(), ids=_slice_id)
def test_a_handler_gates_on_the_command_name_it_declares(handler: Path) -> None:
    tree = ast.parse(handler.read_text(encoding="utf-8"))
    calls = _authorize_calls(tree)
    assert len(calls) == 1, (
        f"{_slice_id(handler)} makes {len(calls)} authorize calls. Every command "
        "and every query passes exactly one gate, and a slice with two is asking "
        "a reader which one decides."
    )

    passed = [kw.value for kw in calls[0].keywords if kw.arg == "command_name"]
    assert len(passed) == 1, (
        f"{_slice_id(handler)} does not pass command_name= to authorize. Pass it "
        "by keyword: the port takes principal, command and surface, and two of "
        "the three are easy to swap positionally."
    )

    gate = passed[0]
    assert isinstance(gate, ast.Name) and gate.id == "_COMMAND_NAME", (
        f"{_slice_id(handler)} authorizes under {ast.unparse(gate)} rather than "
        "_COMMAND_NAME. A slice names its command once, so the gate it runs, the "
        "label on its events and its log lines cannot disagree. A literal is "
        "refused here even when it is the right literal, because the next edit "
        "to the constant will not reach it."
    )
