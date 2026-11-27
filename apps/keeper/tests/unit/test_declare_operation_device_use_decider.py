"""The decision that declaring an operation's device use produces.

Three refusals and one event. The refusals worth separating are the two
that share a class, because what the error carries is the only thing
telling a caller whether its operation is retired or declared already,
and which way.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from keeper.execution.aggregates.operation import (
    Operation,
    OperationDeviceUseCannotBeDeclaredError,
    OperationDeviceUseDeclared,
    OperationName,
    OperationNotFoundError,
    OperationStatus,
)
from keeper.execution.features.declare_operation_device_use import (
    DeclareOperationDeviceUse,
    decide,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_ID = UUID(int=7)


def _operation(
    status: OperationStatus = OperationStatus.ACTIVE, drives_devices: bool | None = None
) -> Operation:
    return Operation(
        id=_ID,
        name=OperationName("move"),
        parameters_schema=_SCHEMA,
        status=status,
        drives_devices=drives_devices,
    )


@pytest.mark.parametrize("drives_devices", [True, False])
def test_declaring_an_undeclared_operation_emits_the_value_at_the_moment_given(
    drives_devices: bool,
) -> None:
    events = decide(
        _operation(),
        DeclareOperationDeviceUse(operation_id=_ID, drives_devices=drives_devices),
        now=_NOW,
    )

    assert events == [
        OperationDeviceUseDeclared(
            operation_id=_ID, drives_devices=drives_devices, occurred_at=_NOW
        )
    ]


def test_declaring_an_operation_nobody_defined_is_refused() -> None:
    with pytest.raises(OperationNotFoundError):
        decide(None, DeclareOperationDeviceUse(operation_id=_ID, drives_devices=True), now=_NOW)


@pytest.mark.parametrize(("held", "asked"), [(True, True), (True, False), (False, True)])
def test_a_second_declaration_is_refused_whichever_way_it_points_and_names_the_first(
    held: bool, asked: bool
) -> None:
    with pytest.raises(OperationDeviceUseCannotBeDeclaredError) as caught:
        decide(
            _operation(drives_devices=held),
            DeclareOperationDeviceUse(operation_id=_ID, drives_devices=asked),
            now=_NOW,
        )

    assert caught.value.drives_devices is held
    assert caught.value.status is OperationStatus.ACTIVE
    assert f"already declared drives_devices = {str(held).lower()}" in str(caught.value)


def test_declaring_a_retired_operation_is_refused_and_says_it_is_retired() -> None:
    with pytest.raises(OperationDeviceUseCannotBeDeclaredError, match="Retired") as caught:
        decide(
            _operation(OperationStatus.RETIRED),
            DeclareOperationDeviceUse(operation_id=_ID, drives_devices=False),
            now=_NOW,
        )

    assert caught.value.drives_devices is None


def test_a_retired_operation_declared_earlier_hears_that_it_is_retired() -> None:
    """Retirement is asked first, because a declaration would govern nothing,
    and the held value still rides the error for a caller that wants it."""
    with pytest.raises(OperationDeviceUseCannotBeDeclaredError, match="Retired") as caught:
        decide(
            _operation(OperationStatus.RETIRED, drives_devices=True),
            DeclareOperationDeviceUse(operation_id=_ID, drives_devices=False),
            now=_NOW,
        )

    assert (caught.value.status, caught.value.drives_devices) == (OperationStatus.RETIRED, True)
