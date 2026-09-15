"""Test function names state the property, not just the subject.

`test_<subject>_<scenario>_<expectation>`. Long is fine. A name that stops at
the subject (`test_handler`, `test_register_thing`) tells a reader which code
ran but not what was supposed to be true of it, so a failure report names a
function rather than a broken promise.

The heuristic is deliberately loose: a minimum word count plus a ban on the
vaguest endings. It catches `test_handler_works`, not every weak name. A
tighter rule would reject legitimate names and get suppressed.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

import ast

import pytest

from tests.architecture.conftest import tracked_test_files

pytestmark = pytest.mark.architecture

MIN_WORDS = 4
"""`test_` plus at least three more words. `test_decide_emits_x` clears it."""

VAGUE_ENDINGS = frozenset({"works", "ok", "correct", "good", "valid", "test", "it"})


def test_every_test_function_name_states_an_outcome() -> None:
    offenders: list[str] = []
    for path in sorted(tracked_test_files()):
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not node.name.startswith("test_"):
                continue
            words = node.name.split("_")
            if len(words) < MIN_WORDS:
                offenders.append(f"{path.name}:{node.lineno}: {node.name} (too few words)")
            elif words[-1] in VAGUE_ENDINGS:
                offenders.append(f"{path.name}:{node.lineno}: {node.name} (vague ending)")
    assert not offenders, "Test names that name a subject but not an outcome:\n" + "\n".join(
        offenders
    )
