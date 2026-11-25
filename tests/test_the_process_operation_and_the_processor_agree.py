"""The process operation, against the names the conductor's processor reads.

`beamlines/operations.toml` declares `process` and the parameters a step
may carry. `apps/conductor/src/conductor/adapters/globus_compute.py`
reads those parameters by name and spells the places and configurations
it will accept. `apps/conductor/infra/computing/reconstructions.py` names
the routine the processor answers to by default and the settings a run
works out for itself, which no configuration may hold, and each
`beamlines/<name>/processing.toml` holds the configurations a processor
is handed. `apps/reporter/src/reporter/placing.py` reads the operation
name and the two parameters saying where a finished process wrote, to
record its output in custody. That is one agreement written in five
places across three of them, and nothing else reads it whole.

## Why drift here is quiet

A parameter renamed on one side passes every check on both. The keeper
accepts the step because it satisfies the schema, and the engine refuses
it at the far end of a dispatch rather than in a test. A default routine
that differs from the operation's name is a conductor offered nothing,
which reads as a quiet beamline. A configuration holding a setting the
profile derives is one the processor refuses at startup, on a host. A
watcher reading other names finds no finished process and records no
output, and says nothing about it.

## Why the words are read rather than imported

This tier installs neither project, so what is compared is a handful of
literals, the choice the check on the move operation makes for the same
reason.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Any

TREE = Path(__file__).resolve().parents[1]
REGISTER = TREE / "beamlines" / "operations.toml"
CONDUCTOR = TREE / "apps" / "conductor"
ADAPTER = CONDUCTOR / "src" / "conductor" / "adapters" / "globus_compute.py"
PROFILE = CONDUCTOR / "infra" / "computing" / "reconstructions.py"
WATCHER = TREE / "apps" / "reporter" / "src" / "reporter" / "placing.py"

OPERATION = "process"
REQUIRED = ("CONFIG", "AT", "INPUT", "OUTPUT")
OPTIONAL = ("OVERRIDE",)
"""The adapter's names for what a process step carries, required and not."""


def _assigned(module: Path, name: str) -> ast.expr:
    """The value of a module-level assignment to `name`, annotated or not."""
    tree = ast.parse(module.read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return node.value
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return node.value
    raise AssertionError(f"{module.relative_to(TREE)} no longer declares {name}")


def _string(module: Path, name: str) -> str:
    value = _assigned(module, name)
    assert isinstance(value, ast.Constant) and isinstance(value.value, str), (
        f"{name} in {module.relative_to(TREE)} is no longer a string literal"
    )
    return value.value


def _compiled(module: Path, name: str) -> str:
    value = _assigned(module, name)
    assert isinstance(value, ast.Call) and value.args, f"{name} is no longer re.compile"
    pattern = value.args[0]
    assert isinstance(pattern, ast.Constant) and isinstance(pattern.value, str)
    return pattern.value


def _derived() -> set[str]:
    value = _assigned(PROFILE, "DERIVED")
    assert isinstance(value, ast.Call) and value.args, "DERIVED is no longer frozenset({...})"
    members = value.args[0]
    assert isinstance(members, ast.Set), "DERIVED is no longer built from a set literal"
    found = {m.value for m in members.elts if isinstance(m, ast.Constant)}
    assert all(isinstance(m, str) for m in found)
    return {str(m) for m in found}


def _schema() -> dict[str, Any]:
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    for operation in register.get("operation", []):
        if operation.get("name") == OPERATION:
            schema: dict[str, Any] = operation["parameters_schema"]
            return schema
    raise AssertionError(f"{REGISTER.relative_to(TREE)} no longer declares {OPERATION!r}")


def _configurations() -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for path in sorted((TREE / "beamlines").glob("*/processing.toml")):
        document = tomllib.loads(path.read_text(encoding="utf-8"))
        for name, settings in document.get("config", {}).items():
            found[f"{path.parent.name} {name}"] = settings
    return found


def test_every_side_still_declares_what_this_rule_compares() -> None:
    """The guard on the comparisons below, which are the point of the file."""
    assert _schema()["required"]
    assert all(_string(ADAPTER, name) for name in REQUIRED + OPTIONAL)
    assert _string(PROFILE, "DEFAULT_PROCESS_ROUTINE")
    assert _string(WATCHER, "PROCESS")
    assert _derived()
    assert _configurations()


def test_the_parameters_the_register_declares_are_the_ones_the_processor_reads() -> None:
    required = {_string(ADAPTER, name) for name in REQUIRED}
    optional = {_string(ADAPTER, name) for name in OPTIONAL}
    schema = _schema()

    assert set(schema["required"]) == required
    assert set(schema["properties"]) == required | optional


def test_the_watcher_reads_the_operation_and_the_parameters_saying_where_a_process_wrote() -> None:
    assert _string(WATCHER, "PROCESS") == OPERATION
    assert _string(WATCHER, "AT") == _string(ADAPTER, "AT")
    assert _string(WATCHER, "OUTPUT") == _string(ADAPTER, "OUTPUT")


def test_the_processor_answers_by_default_to_the_operations_own_name() -> None:
    assert _string(PROFILE, "DEFAULT_PROCESS_ROUTINE") == OPERATION


def test_a_place_or_configuration_the_register_accepts_is_one_the_processor_can_spell() -> None:
    """Patterns rather than lists, so the keeper freezes a spelling and not a set of names."""
    spelled = f"^{_compiled(ADAPTER, '_NAME')}$"
    properties = _schema()["properties"]

    for name in ("CONFIG", "AT"):
        parameter = _string(ADAPTER, name)
        assert properties[parameter]["pattern"] == spelled, (
            f"{REGISTER.relative_to(TREE)} spells {parameter!r} as "
            f"{properties[parameter]['pattern']!r} and the processor as {spelled!r}"
        )


def test_no_configuration_holds_a_setting_a_run_works_out_for_itself() -> None:
    derived = _derived()
    clashing = {
        where: sorted(set(settings) & derived)
        for where, settings in _configurations().items()
        if set(settings) & derived
    }
    assert not clashing, (
        f"{clashing} would point every run at one file, and the processor refuses such a "
        "configuration when it is built"
    )


def test_every_configuration_is_spelled_the_way_a_process_step_may_name_it() -> None:
    spelled = _compiled(ADAPTER, "_NAME")
    unspellable = [
        where for where in _configurations() if not re.fullmatch(spelled, where.split(" ", 1)[1])
    ]
    assert not unspellable
