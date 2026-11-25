"""The move operation, against the names the conductor's mover and the reporter's watcher read.

`beamlines/operations.toml` declares `move` and the parameters a step may
carry. `apps/conductor/src/conductor/adapters/globus_transfer.py` reads
those parameters by name and spells the places it will accept, and
`apps/conductor/infra/transferring/transfers.py` names the routine the
mover answers to by default. `apps/reporter/src/reporter/placing.py`
reads the same operation name and parameters off a finished step, to
record where its data arrived. That is one agreement written in three
places across three projects, and nothing else reads it whole: the
keeper validates a step against the schema, each program reads whatever
names it was written with, and neither project's suite can see the
register.

## Why drift here is quiet

A parameter renamed on one side passes every check on both. The keeper
accepts the step because it satisfies the schema, and the engine refuses
it as naming no path at the far end of a dispatch rather than in a test.
A default routine that differs from the operation's name is a conductor
offered nothing, which reads as a quiet beamline. A place the register
lists in a spelling no deployment can write is a move the keeper accepts
and every conductor refuses.

## Why the words are read rather than imported

This tier installs neither project. What is compared is a handful of
string literals either way, which is the reasoning the check on hopeless
transfer faults gives for the same choice.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Any

TREE = Path(__file__).resolve().parents[1]
REGISTER = TREE / "beamlines" / "operations.toml"
ADAPTER = TREE / "apps" / "conductor" / "src" / "conductor" / "adapters" / "globus_transfer.py"
PROFILE = TREE / "apps" / "conductor" / "infra" / "transferring" / "transfers.py"
WATCHER = TREE / "apps" / "reporter" / "src" / "reporter" / "placing.py"

OPERATION = "move"
PARAMETERS = ("PATH", "FROM", "TO")
"""The adapter's names for the three parameters a move carries."""


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


def _schema() -> dict[str, Any]:
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    for operation in register.get("operation", []):
        if operation.get("name") == OPERATION:
            schema: dict[str, Any] = operation["parameters_schema"]
            return schema
    raise AssertionError(f"{REGISTER.relative_to(TREE)} no longer declares {OPERATION!r}")


def test_both_projects_still_declare_what_this_rule_compares() -> None:
    """The guard on the comparisons below, which are the point of the file."""
    assert _schema()["required"]
    assert all(_string(ADAPTER, name) for name in PARAMETERS)
    assert _string(PROFILE, "DEFAULT_MOVE_ROUTINE")


def test_the_parameters_the_register_requires_are_the_ones_the_mover_reads() -> None:
    read = {_string(ADAPTER, name) for name in PARAMETERS}
    schema = _schema()

    assert set(schema["required"]) == read
    assert set(schema["properties"]) == read


def test_the_watcher_reads_the_operation_and_parameters_the_register_declares() -> None:
    """A watcher reading other names finds no finished move and records no arrival, quietly."""
    assert _string(WATCHER, "MOVE") == OPERATION
    assert {_string(WATCHER, name) for name in PARAMETERS} == set(_schema()["required"])


def test_the_mover_answers_by_default_to_the_operations_own_name() -> None:
    assert _string(PROFILE, "DEFAULT_MOVE_ROUTINE") == OPERATION


def test_a_move_may_arrive_at_every_place_it_may_leave() -> None:
    properties = _schema()["properties"]
    leaving = properties[_string(ADAPTER, "FROM")]["enum"]
    arriving = properties[_string(ADAPTER, "TO")]["enum"]

    assert leaving
    assert sorted(leaving) == sorted(arriving)


def test_every_place_the_register_lists_is_one_a_deployment_can_spell() -> None:
    spelled = _assigned(ADAPTER, "_PLACE_NAME")
    assert isinstance(spelled, ast.Call) and spelled.args, "_PLACE_NAME is no longer re.compile"
    pattern = spelled.args[0]
    assert isinstance(pattern, ast.Constant) and isinstance(pattern.value, str)
    places = _schema()["properties"][_string(ADAPTER, "FROM")]["enum"]

    unspellable = [place for place in places if not re.fullmatch(pattern.value, place)]
    assert not unspellable, (
        f"{REGISTER.relative_to(TREE)} lists {unspellable} as places, and the mover refuses "
        "those spellings in a deployment's settings, so every move to them would be refused."
    )
