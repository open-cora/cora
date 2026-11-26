"""The setups each beamline holds, and the rows that name them.

A step whose operation takes a setup names one with `config` and may
override a setting it holds, and nothing else. A beamline keeps the setups
each such operation runs with in a register of its own, named for the
operation the way `seed_setups.OPERATIONS_BY_REGISTER` says:
`processing.toml` for `process` and `collection.toml` for `collect`.

The keeper holds a row to that rule when the procedure is defined, which is
when a register is seeded at the facility, against setups seeded from these
same files. This holds it when the row is written, so a row the keeper
would refuse never reaches a seeding run.

## Why the rule is a function and is run twice

No row overrides anything today, so a check over the real rows alone would
range over nothing and pass while checking nothing. The rule is one
function, run over the registers and over rows made to break it.
"""

import re
import tomllib
from pathlib import Path
from typing import cast

import pytest

from descriptor import RunStep, load_operations, load_procedures
from seed_setups import OPERATIONS_BY_REGISTER

BEAMLINES = Path(__file__).parents[1]

PINNED_SETUPS = {
    ("19-bm", "collection.toml"): ["smoke-19bm"],
    ("19-bm", "processing.toml"): ["tomocupy-19bm"],
}
"""The setups each register holds, by beamline and register.

Pinned so the checks below range over something: a register that lost its
tables would pass every one of them.
"""

HELD = sorted(
    (path.parent.name, register)
    for register in OPERATIONS_BY_REGISTER
    for path in BEAMLINES.glob(f"*/{register}")
)
WITH_PROCEDURES = sorted(path.parent.name for path in BEAMLINES.glob("*/procedures.toml"))
EVERY_PAIRING = [
    (beamline, register) for beamline in WITH_PROCEDURES for register in OPERATIONS_BY_REGISTER
]

Step = tuple[str, dict[str, object]]


def _tables(beamline: str, register: str) -> dict[str, object]:
    """The tables under `config` in one of a beamline's setup registers, as parsed."""
    path = BEAMLINES / beamline / register
    if not path.is_file():
        return {}
    tables: dict[str, object] = tomllib.loads(path.read_text(encoding="utf-8")).get("config", {})
    return tables


def _setups(beamline: str, register: str) -> dict[str, dict[str, object]]:
    return {
        name: cast("dict[str, object]", table)
        for name, table in _tables(beamline, register).items()
        if isinstance(table, dict)
    }


def _steps(beamline: str, operation: str) -> list[Step]:
    register = load_procedures(BEAMLINES / beamline / "procedures.toml")
    return [
        (procedure.name, dict(step.parameters))
        for procedure in register.procedures
        for step in procedure.steps
        if isinstance(step, RunStep) and step.operation == operation
    ]


def _pattern(operation: str, parameter: str) -> str:
    for entry in load_operations(BEAMLINES / "operations.toml").operations:
        if entry.name == operation:
            pattern: str = entry.parameters_schema["properties"][parameter]["pattern"]
            return pattern
    raise AssertionError(f"operations.toml no longer declares {operation!r}")


def _unheld(steps: list[Step], setups: dict[str, dict[str, object]]) -> list[str]:
    """What the keeper would refuse in these steps, given these setups."""
    found: list[str] = []
    for name, parameters in steps:
        config = str(parameters.get("config"))
        held = setups.get(config)
        if held is None:
            found.append(f"{name!r} names {config!r}, which no setup here is called")
            continue
        given: object = parameters.get("override") or {}
        assert isinstance(given, dict), f"{name!r} has an override that is not a table"
        override = cast("dict[str, object]", given)
        found.extend(
            f"{name!r} overrides {key!r}, which {config!r} does not hold"
            for key in sorted(set(override) - set(held))
        )
    return found


def test_the_setups_each_register_holds_are_the_ones_pinned() -> None:
    found = {
        (beamline, register): sorted(_setups(beamline, register)) for beamline, register in HELD
    }
    assert found == PINNED_SETUPS


@pytest.mark.parametrize("operation", sorted(OPERATIONS_BY_REGISTER.values()))
def test_every_operation_taking_a_setup_has_a_row_held_to_the_rule_below(operation: str) -> None:
    assert any(_steps(beamline, operation) for beamline in WITH_PROCEDURES)


@pytest.mark.parametrize(("beamline", "register"), EVERY_PAIRING)
def test_every_row_names_a_held_setup_and_overrides_only_its_settings(
    beamline: str, register: str
) -> None:
    steps = _steps(beamline, OPERATIONS_BY_REGISTER[register])
    found = _unheld(steps, _setups(beamline, register))
    assert not found, "\n".join(found)


def test_a_row_naming_a_setup_nobody_holds_is_found() -> None:
    found = _unheld([("Process", {"config": "tomocupy-2bm"})], _setups("19-bm", "processing.toml"))
    assert found == ["'Process' names 'tomocupy-2bm', which no setup here is called"]


def test_a_row_naming_a_setup_held_only_for_another_operation_is_found() -> None:
    step: Step = ("Smoke-test scan", {"config": "tomocupy-19bm"})
    found = _unheld([step], _setups("19-bm", "collection.toml"))
    assert found == ["'Smoke-test scan' names 'tomocupy-19bm', which no setup here is called"]


def test_a_row_overriding_a_setting_its_setup_does_not_hold_is_found() -> None:
    step: Step = ("Process", {"config": "tomocupy-19bm", "override": {"rotation-axes": 1630.0}})
    found = _unheld([step], _setups("19-bm", "processing.toml"))
    assert found == ["'Process' overrides 'rotation-axes', which 'tomocupy-19bm' does not hold"]


def test_a_row_overriding_a_setting_its_setup_holds_is_not_found() -> None:
    step: Step = ("Smoke-test scan", {"config": "smoke-19bm", "override": {"NumAngles": 32}})
    assert _unheld([step], _setups("19-bm", "collection.toml")) == []


@pytest.mark.parametrize(("beamline", "register"), HELD)
def test_every_setup_is_named_in_the_spelling_a_step_may_use(beamline: str, register: str) -> None:
    operation = OPERATIONS_BY_REGISTER[register]
    pattern = _pattern(operation, "config")
    unspellable = [name for name in _setups(beamline, register) if not re.search(pattern, name)]
    assert not unspellable, f"{beamline} holds {unspellable}, which no {operation} step can name"


@pytest.mark.parametrize(("beamline", "register"), HELD)
def test_every_setup_is_a_table_holding_at_least_one_setting(beamline: str, register: str) -> None:
    empty = [
        name
        for name, settings in _tables(beamline, register).items()
        if not isinstance(settings, dict) or not settings
    ]
    assert not empty, f"{beamline}'s {register} holds {empty}, which name no setting to write"
