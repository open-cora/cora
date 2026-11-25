"""The configurations each beamline's processor holds, and the process rows that name them.

A process step names a configuration and may override a setting that
configuration holds, and nothing else. The keeper cannot hold a row to
that: its schema subset can say `override` is a table and cannot say which
keys the table may carry, and the configurations belong to a deployment
rather than to the record. The conductor refuses such a step when it is
dispatched, which is late, so the agreement is held here, when the row is
written.

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

BEAMLINES = Path(__file__).parents[1]
PROCESS = "process"

PINNED_CONFIGURATIONS = {"19-bm": ["tomocupy-19bm"]}
"""The configurations each processing.toml holds, by beamline.

Pinned so the checks below range over something: a configurations file
that lost its tables would pass every one of them.
"""

WITH_PROCESSING = sorted(path.parent.name for path in BEAMLINES.glob("*/processing.toml"))
WITH_PROCEDURES = sorted(path.parent.name for path in BEAMLINES.glob("*/procedures.toml"))

Step = tuple[str, dict[str, object]]


def _tables(beamline: str) -> dict[str, object]:
    """The tables under `config` in a beamline's processing.toml, as parsed."""
    path = BEAMLINES / beamline / "processing.toml"
    if not path.is_file():
        return {}
    tables: dict[str, object] = tomllib.loads(path.read_text(encoding="utf-8")).get("config", {})
    return tables


def _configurations(beamline: str) -> dict[str, dict[str, object]]:
    return {
        name: cast("dict[str, object]", table)
        for name, table in _tables(beamline).items()
        if isinstance(table, dict)
    }


def _process_steps(beamline: str) -> list[Step]:
    register = load_procedures(BEAMLINES / beamline / "procedures.toml")
    return [
        (procedure.name, dict(step.parameters))
        for procedure in register.procedures
        for step in procedure.steps
        if isinstance(step, RunStep) and step.operation == PROCESS
    ]


def _pattern(parameter: str) -> str:
    for entry in load_operations(BEAMLINES / "operations.toml").operations:
        if entry.name == PROCESS:
            pattern: str = entry.parameters_schema["properties"][parameter]["pattern"]
            return pattern
    raise AssertionError(f"operations.toml no longer declares {PROCESS!r}")


def _unheld(steps: list[Step], configurations: dict[str, dict[str, object]]) -> list[str]:
    """What a processor holding these configurations would refuse in these steps."""
    found: list[str] = []
    for name, parameters in steps:
        config = str(parameters.get("config"))
        held = configurations.get(config)
        if held is None:
            found.append(f"{name!r} names {config!r}, which no configuration here is called")
            continue
        given: object = parameters.get("override") or {}
        assert isinstance(given, dict), f"{name!r} has an override that is not a table"
        override = cast("dict[str, object]", given)
        found.extend(
            f"{name!r} overrides {key!r}, which {config!r} does not hold"
            for key in sorted(set(override) - set(held))
        )
    return found


def test_the_configurations_each_beamline_holds_are_the_ones_pinned() -> None:
    found = {beamline: sorted(_configurations(beamline)) for beamline in WITH_PROCESSING}
    assert found == PINNED_CONFIGURATIONS


def test_at_least_one_process_row_is_held_to_the_rule_below() -> None:
    assert any(_process_steps(beamline) for beamline in WITH_PROCEDURES)


@pytest.mark.parametrize("beamline", WITH_PROCEDURES)
def test_every_process_row_names_a_held_configuration_and_overrides_only_its_settings(
    beamline: str,
) -> None:
    found = _unheld(_process_steps(beamline), _configurations(beamline))
    assert not found, "\n".join(found)


def test_a_row_naming_a_configuration_nobody_holds_is_found() -> None:
    found = _unheld([("Process", {"config": "tomocupy-2bm"})], _configurations("19-bm"))
    assert found == ["'Process' names 'tomocupy-2bm', which no configuration here is called"]


def test_a_row_overriding_a_setting_its_configuration_does_not_hold_is_found() -> None:
    step: Step = ("Process", {"config": "tomocupy-19bm", "override": {"rotation-axes": 1630.0}})
    found = _unheld([step], _configurations("19-bm"))
    assert found == ["'Process' overrides 'rotation-axes', which 'tomocupy-19bm' does not hold"]


def test_a_row_overriding_a_setting_its_configuration_holds_is_not_found() -> None:
    step: Step = ("Process", {"config": "tomocupy-19bm", "override": {"rotation-axis": 1630.0}})
    assert _unheld([step], _configurations("19-bm")) == []


@pytest.mark.parametrize("beamline", WITH_PROCESSING)
def test_every_configuration_is_named_in_the_spelling_a_process_step_may_use(
    beamline: str,
) -> None:
    pattern = _pattern("config")
    unspellable = [name for name in _configurations(beamline) if not re.search(pattern, name)]
    assert not unspellable, f"{beamline} holds {unspellable}, which no process step can name"


@pytest.mark.parametrize("beamline", WITH_PROCESSING)
def test_every_configuration_is_a_table_holding_at_least_one_setting(beamline: str) -> None:
    empty = [
        name
        for name, settings in _tables(beamline).items()
        if not isinstance(settings, dict) or not settings
    ]
    assert not empty, f"{beamline} holds {empty}, which the processor refuses at startup"
