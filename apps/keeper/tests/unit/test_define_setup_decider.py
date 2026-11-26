"""The decision that defining a setup produces.

Most of what a setup can be refused for is refused here, because the
decider is the one place both surfaces pass through. The operation and the
key arrive in the context, so each refusal that depends on them is driven
by building a context rather than by a store.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.operation import (
    Operation,
    OperationCannotBeCitedError,
    OperationName,
    OperationStatus,
)
from keeper.execution.aggregates.setup import (
    InvalidSetupBeamlineError,
    InvalidSetupNameError,
    InvalidSetupSettingsError,
    InvalidSetupSettingsSchemaError,
    OperationCannotTakeSetupError,
    Setup,
    SetupAlreadyExistsError,
    SetupBeamline,
    SetupDefined,
    SetupName,
)
from keeper.execution.features.define_setup import DefineSetup, DefineSetupContext, decide

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)

_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "config": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
        "override": {"type": "object"},
    },
}
"""The two parameters that let a run name a setup, and nothing else."""

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "rotation-axis": {"type": "number", "unit": {"system": "udunits", "code": "pixel"}},
        "binning": {"type": "integer", "enum": [1, 2, 4]},
    },
}

_SETTINGS: dict[str, Any] = {"rotation-axis": 1630.0, "binning": 2}


def _operation(
    *, schema: dict[str, Any] | None = None, status: OperationStatus = OperationStatus.ACTIVE
) -> Operation:
    return Operation(
        id=uuid4(),
        name=OperationName("process"),
        parameters_schema=schema if schema is not None else dict(_PROCESS_SCHEMA),
        status=status,
    )


def _command(operation: Operation, **overrides: Any) -> DefineSetup:
    fields: dict[str, Any] = {
        "beamline": "2-bm",
        "operation_id": operation.id,
        "name": "tomo-default",
        "settings": dict(_SETTINGS),
        "settings_schema": dict(_SETTINGS_SCHEMA),
    }
    fields.update(overrides)
    return DefineSetup(**fields)


def _decide(
    command: DefineSetup,
    operation: Operation,
    *,
    existing: UUID | None = None,
    new_id: UUID | None = None,
) -> list[SetupDefined]:
    return decide(
        None,
        command,
        context=DefineSetupContext(operation=operation, existing_setup_id=existing),
        now=_NOW,
        new_id=new_id or uuid4(),
    )


def test_defining_a_setup_emits_one_event_carrying_the_whole_of_it() -> None:
    operation = _operation()
    new_id = uuid4()

    events = _decide(_command(operation), operation, new_id=new_id)

    assert events == [
        SetupDefined(
            setup_id=new_id,
            beamline="2-bm",
            operation_id=operation.id,
            setup_name="tomo-default",
            settings=_SETTINGS,
            settings_schema=_SETTINGS_SCHEMA,
            occurred_at=_NOW,
        )
    ]


def test_the_emitted_beamline_is_the_trimmed_one() -> None:
    operation = _operation()

    events = _decide(_command(operation, beamline="  2-bm  "), operation)

    assert events[0].beamline == "2-bm"


def test_defining_a_setup_on_a_live_stream_is_refused() -> None:
    operation = _operation()
    existing = Setup(
        id=uuid4(),
        beamline=SetupBeamline("2-bm"),
        operation_id=operation.id,
        name=SetupName("tomo-default"),
        settings=dict(_SETTINGS),
        settings_schema=dict(_SETTINGS_SCHEMA),
        revision=1,
    )

    with pytest.raises(SetupAlreadyExistsError):
        decide(
            existing,
            _command(operation),
            context=DefineSetupContext(operation=operation, existing_setup_id=None),
            now=_NOW,
            new_id=uuid4(),
        )


def test_a_name_no_step_could_carry_is_refused() -> None:
    operation = _operation()

    with pytest.raises(InvalidSetupNameError):
        _decide(_command(operation, name="Tomo Default"), operation)


def test_a_blank_beamline_is_refused() -> None:
    operation = _operation()

    with pytest.raises(InvalidSetupBeamlineError):
        _decide(_command(operation, beamline="   "), operation)


def test_a_setup_for_a_retired_operation_is_refused() -> None:
    operation = _operation(status=OperationStatus.RETIRED)

    with pytest.raises(OperationCannotBeCitedError):
        _decide(_command(operation), operation)


@pytest.mark.parametrize("missing", ["config", "override"])
def test_a_setup_for_an_operation_missing_either_parameter_is_refused(missing: str) -> None:
    schema = {
        **_PROCESS_SCHEMA,
        "properties": {
            name: described
            for name, described in _PROCESS_SCHEMA["properties"].items()
            if name != missing
        },
    }
    operation = _operation(schema=schema)

    with pytest.raises(OperationCannotTakeSetupError, match=str(operation.id)):
        _decide(_command(operation), operation)


def test_a_second_setup_under_a_held_key_is_refused_naming_the_first() -> None:
    operation = _operation()
    holder = uuid4()

    with pytest.raises(SetupAlreadyExistsError, match=str(holder)) as refused:
        _decide(_command(operation), operation, existing=holder)

    assert refused.value.setup_id == holder


def test_a_settings_schema_outside_the_subset_is_refused() -> None:
    operation = _operation()
    settings_schema = {**_SETTINGS_SCHEMA, "additionalProperties": False}

    with pytest.raises(InvalidSetupSettingsSchemaError, match="forbidden keyword"):
        _decide(_command(operation, settings_schema=settings_schema), operation)


def test_settings_that_do_not_match_their_settings_schema_are_refused() -> None:
    operation = _operation()

    with pytest.raises(InvalidSetupSettingsError, match="binning"):
        _decide(_command(operation, settings={**_SETTINGS, "binning": 3}), operation)


def test_a_retired_operation_is_refused_before_a_malformed_settings_schema_is_read() -> None:
    """Values checked against a routine nothing answers to tell the caller
    nothing worth fixing, so the operation is asked about first."""
    operation = _operation(status=OperationStatus.RETIRED)

    with pytest.raises(OperationCannotBeCitedError):
        _decide(_command(operation, settings_schema={"type": "object"}), operation)


def test_a_held_key_is_refused_before_a_malformed_settings_schema_is_read() -> None:
    """A caller told the name is taken should revise the setup already
    there, not fix a document for a definition that will be refused."""
    operation = _operation()

    with pytest.raises(SetupAlreadyExistsError):
        _decide(
            _command(operation, settings_schema={"type": "object"}), operation, existing=uuid4()
        )


def test_a_context_carrying_another_operation_is_a_caller_bug() -> None:
    operation = _operation()

    with pytest.raises(ValueError, match="carries operation"):
        _decide(_command(_operation()), operation)
