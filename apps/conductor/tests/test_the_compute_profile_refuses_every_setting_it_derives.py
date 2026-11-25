"""The settings the compute profile works out for a run, against the ones it refuses from a file.

`infra/computing/reconstructions.py` works out three settings from what a
step names, the input file, the output folder and a logs folder inside
it, and writes them over whatever a configuration or the defaults file
held. `DERIVED` is what it refuses to read from either file. If the two
part, a file holding a setting the profile derives is overwritten for
every run instead of refused at startup, and nobody reading the file
learns that the value in it was never used.

The profile is read rather than imported, because it imports a compute
library this suite does not need.
"""

from __future__ import annotations

import ast
from pathlib import Path

PROFILE = Path(__file__).resolve().parents[1] / "infra" / "computing" / "reconstructions.py"


def _module() -> ast.Module:
    return ast.parse(PROFILE.read_text(encoding="utf-8"))


def _written_by_job() -> set[str]:
    """The keys `_job` assigns into the arguments it renders."""
    for node in ast.walk(_module()):
        if isinstance(node, ast.FunctionDef) and node.name == "_job":
            return {
                str(target.slice.value)
                for statement in ast.walk(node)
                if isinstance(statement, ast.Assign)
                for target in statement.targets
                if isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "args"
                and isinstance(target.slice, ast.Constant)
            }
    raise AssertionError("the compute profile no longer has a _job")


def _derived() -> set[str]:
    for node in _module().body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "DERIVED"
            and isinstance(node.value, ast.Call)
            and node.value.args
            and isinstance(node.value.args[0], ast.Set)
        ):
            return {
                str(member.value)
                for member in node.value.args[0].elts
                if isinstance(member, ast.Constant)
            }
    raise AssertionError("the compute profile no longer declares DERIVED as a set literal")


def test_the_settings_a_run_works_out_are_exactly_the_ones_a_file_may_not_hold() -> None:
    written = _written_by_job()

    assert written, "the comparison below would pass over nothing"
    assert written == _derived()
