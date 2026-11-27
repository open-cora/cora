"""The Operation aggregate: its name value object, its fold, and its round trip.

The round trip is the load-bearing one. A payload leaves as primitives
and comes back as a value object, and the two halves are written in
different modules, so nothing but a test run against both at once says
they still agree.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.execution.aggregates.operation import (
    OPERATION_NAME_MAX_LENGTH,
    OPERATION_STREAM_TYPE,
    InvalidOperationNameError,
    OperationDefined,
    OperationDeviceUseDeclared,
    OperationName,
    OperationRetired,
    OperationStatus,
    fold,
    from_stored,
    to_payload,
)
from keeper.infrastructure.ports.event_store import StoredEvent

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 18, 9, 30, tzinfo=UTC)

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


def _stored(event_type: str, payload: dict[str, object]) -> StoredEvent:
    """A stored row carrying the given type and payload, envelope filled in."""
    return StoredEvent(
        position=1,
        event_id=uuid4(),
        stream_type=OPERATION_STREAM_TYPE,
        stream_id=uuid4(),
        version=1,
        event_type=event_type,
        schema_version=1,
        payload=dict(payload),
        correlation_id=uuid4(),
        causation_id=None,
        occurred_at=_WHEN,
        recorded_at=_WHEN,
    )


def _defined(name: str = "count") -> OperationDefined:
    return OperationDefined(
        operation_id=uuid4(),
        operation_name=name,
        parameters_schema=_SCHEMA,
        occurred_at=_WHEN,
    )


def test_a_plan_name_is_trimmed_on_construction() -> None:
    assert OperationName("  count  ").value == "count"


def test_a_plan_name_that_is_only_whitespace_is_refused() -> None:
    with pytest.raises(InvalidOperationNameError):
        OperationName("   ")


def test_a_plan_name_over_the_length_bound_is_refused() -> None:
    with pytest.raises(InvalidOperationNameError):
        OperationName("x" * (OPERATION_NAME_MAX_LENGTH + 1))


def test_a_plan_name_at_the_length_bound_is_accepted() -> None:
    """The bound is inclusive, which an off-by-one would quietly move."""
    at_the_bound = "x" * OPERATION_NAME_MAX_LENGTH
    assert OperationName(at_the_bound).value == at_the_bound


def test_the_stored_payload_carries_the_name_under_a_qualified_key() -> None:
    """The payload boundary, asserted on the payload itself.

    `operation_name` rather than `name` is what keeps this row past the
    personal-data check, and that check reads the event class, not this
    dict. A payload key renamed without the field would pass there and
    break only the round trip, which is a longer way round to the same
    news.
    """
    event = _defined()

    assert to_payload(event) == {
        "operation_id": str(event.operation_id),
        "operation_name": "count",
        "parameters_schema": _SCHEMA,
        "occurred_at": _WHEN.isoformat(),
    }


def test_folding_the_genesis_event_gives_the_plan_it_describes() -> None:
    event = _defined()

    operation = fold([event])

    assert operation is not None
    assert operation.id == event.operation_id
    assert operation.name == OperationName("count")
    assert operation.parameters_schema == _SCHEMA
    assert operation.status is OperationStatus.ACTIVE


def test_a_retirement_retires_the_operation_and_changes_nothing_else() -> None:
    """A retired operation is still the record of what was written down, so
    a procedure composed against its schema can still be read against it."""
    defined = _defined()

    operation = fold(
        [defined, OperationRetired(operation_id=defined.operation_id, occurred_at=_WHEN)]
    )

    assert operation is not None
    assert operation.status is OperationStatus.RETIRED
    assert operation.is_retired
    assert operation.name == OperationName("count")
    assert operation.parameters_schema == _SCHEMA


def test_a_retirement_on_an_empty_stream_cannot_be_folded() -> None:
    with pytest.raises(ValueError, match="OperationRetired cannot be applied to empty state"):
        fold([OperationRetired(operation_id=uuid4(), occurred_at=_WHEN)])


def test_a_retirement_survives_the_round_trip_through_its_stored_payload() -> None:
    event = OperationRetired(operation_id=uuid4(), occurred_at=_WHEN)

    assert to_payload(event) == {
        "operation_id": str(event.operation_id),
        "occurred_at": _WHEN.isoformat(),
    }
    assert from_stored(_stored("OperationRetired", to_payload(event))) == event


def test_folding_an_empty_stream_gives_no_plan() -> None:
    assert fold([]) is None


def test_the_folded_schema_is_not_the_payload_dict_it_came_from() -> None:
    """Shallow copy on fold, so neither side can mutate the other.

    The immutable-collection rule in docs/reference/modeling.md cannot
    cover a JSON Schema field, because a schema is freeform by nature
    and no immutable type fits it. The copy is the defence that replaces
    it, and an aliasing bug here is silent: the state would look right
    until something wrote through one reference and changed the other.
    """
    event = _defined()

    operation = fold([event])

    assert operation is not None
    assert operation.parameters_schema == event.parameters_schema
    assert operation.parameters_schema is not event.parameters_schema


def test_an_event_survives_the_round_trip_through_its_stored_payload() -> None:
    event = _defined("grid_scan")

    assert from_stored(_stored("OperationDefined", to_payload(event))) == event


def test_a_stored_row_of_an_unknown_event_type_is_refused() -> None:
    with pytest.raises(ValueError, match="Unknown Operation event_type"):
        from_stored(_stored("PlanRetired", to_payload(_defined())))


def test_a_stored_row_missing_a_field_is_refused_by_event_not_by_field() -> None:
    """The wrap is what makes the error name the event.

    Without it a bad row raises `KeyError` from inside the builder, which
    says which field was missing and not which event could not be
    rebuilt. The caller has the row and can find the field; what it
    cannot recover is the shape the row was meant to have.
    """
    payload = to_payload(_defined())
    del payload["operation_name"]

    with pytest.raises(ValueError, match="Malformed OperationDefined"):
        from_stored(_stored("OperationDefined", payload))


def test_a_stored_row_whose_name_no_longer_passes_the_bound_fails_the_fold() -> None:
    """Re-validation on the way out, not just on the way in.

    A row can only hold a name the decider accepted, so this state is
    unreachable through the API today. It becomes reachable the day the
    bound is tightened, and the fold refusing is what turns that into a
    visible failure rather than an operation whose name nothing could have
    written.
    """
    payload = to_payload(_defined())
    payload["operation_name"] = "x" * (OPERATION_NAME_MAX_LENGTH + 1)

    with pytest.raises(InvalidOperationNameError):
        fold([from_stored(_stored("OperationDefined", payload))])


def test_a_definition_alone_folds_into_an_operation_nobody_has_declared() -> None:
    operation = fold([_defined()])

    assert operation is not None
    assert operation.drives_devices is None


@pytest.mark.parametrize("drives_devices", [True, False])
def test_a_declaration_sets_the_device_use_and_changes_nothing_else(drives_devices: bool) -> None:
    defined = _defined()

    operation = fold(
        [
            defined,
            OperationDeviceUseDeclared(
                operation_id=defined.operation_id, drives_devices=drives_devices, occurred_at=_WHEN
            ),
        ]
    )

    assert operation is not None
    assert operation.drives_devices is drives_devices
    assert (operation.name, operation.status) == (OperationName("count"), OperationStatus.ACTIVE)


def test_a_declaration_on_an_empty_stream_cannot_be_folded() -> None:
    with pytest.raises(ValueError, match="OperationDeviceUseDeclared cannot be applied"):
        fold(
            [
                OperationDeviceUseDeclared(
                    operation_id=uuid4(), drives_devices=True, occurred_at=_WHEN
                )
            ]
        )


def test_a_declaration_survives_the_round_trip_through_its_stored_payload() -> None:
    event = OperationDeviceUseDeclared(
        operation_id=uuid4(), drives_devices=False, occurred_at=_WHEN
    )

    assert to_payload(event) == {
        "operation_id": str(event.operation_id),
        "drives_devices": False,
        "occurred_at": _WHEN.isoformat(),
    }
    assert from_stored(_stored("OperationDeviceUseDeclared", to_payload(event))) == event


def test_a_stored_declaration_that_is_not_a_boolean_is_refused_rather_than_coerced() -> None:
    """`bool("false")` is True, which is the one reading this must never make."""
    payload = to_payload(
        OperationDeviceUseDeclared(operation_id=uuid4(), drives_devices=False, occurred_at=_WHEN)
    )
    payload["drives_devices"] = "false"

    with pytest.raises(ValueError, match="Malformed OperationDeviceUseDeclared"):
        from_stored(_stored("OperationDeviceUseDeclared", payload))
