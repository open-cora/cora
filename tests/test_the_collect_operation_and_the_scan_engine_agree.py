"""The collect operation, against the names the keeper and the scan engine read.

`beamlines/operations.toml` declares `collect` and the parameters a step may
carry. The keeper decides that a run names a setup when its operation
declares both of `SETUP_PARAMETERS`, in
`apps/keeper/src/keeper/execution/aggregates/setup/state.py`, and only then
checks the setup and locks in its revision. The TomoScan engine in
`apps/conductor/src/conductor/adapters/tomoscan_engine.py` reads the setup's
name by `SETUP_NAME` and refuses the parameters it names in `PLACEMENT`.
`beamlines/seed_setups.py` says which register holds which operation's
setups. That is one agreement in four places across three projects, and
nothing else reads it whole.

## Why drift here is quiet

An operation that stopped declaring `override` would still be defined, and
the keeper would stop checking its setups and stop locking in a revision,
with every dispatch still succeeding. An engine reading another name for the
setup would write a record called `config` and be refused by the server at
the far end of a dispatch. A placement parameter renamed on one side would
reach the engine as a setting and be refused there, or worse, be written.

## Why the words are read rather than imported

This tier installs none of the projects, so what is compared is a handful of
literals, the choice the checks on `move` and `process` make for the same
reason.
"""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import Any

TREE = Path(__file__).resolve().parents[1]
REGISTER = TREE / "beamlines" / "operations.toml"
SEEDER = TREE / "beamlines" / "seed_setups.py"
KEEPER_RULE = (
    TREE / "apps" / "keeper" / "src" / "keeper" / "execution" / "aggregates" / "setup" / "state.py"
)
ENGINE = TREE / "apps" / "conductor" / "src" / "conductor" / "adapters" / "tomoscan_engine.py"

OPERATION = "collect"


def _assigned(module: Path, name: str) -> ast.expr:
    """The value of a module-level assignment to `name`, annotated or not."""
    for node in ast.parse(module.read_text(encoding="utf-8")).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            return node.value
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return node.value
    raise AssertionError(f"{module.relative_to(TREE)} no longer declares {name}")


def _literal(module: Path, name: str) -> Any:
    """A literal assigned to `name`, with `frozenset({...})` read as a set."""
    value = _assigned(module, name)
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.args:
        assert value.func.id == "frozenset", f"{name} is no longer a literal"
        return frozenset(ast.literal_eval(value.args[0]))
    return ast.literal_eval(value)


def _schemas() -> dict[str, dict[str, Any]]:
    document = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    return {entry["name"]: entry["parameters_schema"] for entry in document["operation"]}


def _collect() -> dict[str, Any]:
    schemas = _schemas()
    assert OPERATION in schemas, f"operations.toml no longer declares {OPERATION!r}"
    return schemas[OPERATION]


def test_collect_declares_both_parameters_the_keeper_reads_as_naming_a_setup() -> None:
    setup_parameters = _literal(KEEPER_RULE, "SETUP_PARAMETERS")
    assert setup_parameters
    assert set(_collect()["properties"]) >= setup_parameters


def test_the_engine_reads_the_setup_by_the_name_collect_requires() -> None:
    assert _collect()["required"] == [_literal(ENGINE, "SETUP_NAME")]


def test_the_engine_refuses_exactly_the_placement_parameters_collect_declares() -> None:
    placement = _literal(ENGINE, "PLACEMENT")
    declared = set(_collect()["properties"]) - _literal(KEEPER_RULE, "SETUP_PARAMETERS")
    assert placement
    assert set(placement) == declared


def test_every_setups_register_holds_an_operation_that_takes_a_setup() -> None:
    setup_parameters = _literal(KEEPER_RULE, "SETUP_PARAMETERS")
    schemas = _schemas()
    registers: dict[str, str] = _literal(SEEDER, "OPERATIONS_BY_REGISTER")
    assert OPERATION in registers.values()
    for register, operation in registers.items():
        assert operation in schemas, f"{register} is for {operation!r}, which nothing defines"
        properties = set(schemas[operation].get("properties", {}))
        assert properties >= setup_parameters, (
            f"{register} holds setups for {operation!r}, which the keeper never checks one for"
        )
