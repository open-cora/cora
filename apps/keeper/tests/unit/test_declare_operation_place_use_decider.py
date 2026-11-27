"""The decision that declaring an operation's place use produces.

Five refusals and one event. Two refusals share a class, as they do for
device use, and the error is the only thing telling a caller which: a
retired operation, or one already declared and what it says. The other
three are about the declaration itself against the routine it is made
for, and are what keep a parameter that names a place from reading as
one that names nothing.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from keeper.execution.aggregates.operation import (
    InvalidOperationPlaceUseError,
    Operation,
    OperationName,
    OperationNotFoundError,
    OperationPlaceUseCannotBeDeclaredError,
    OperationPlaceUseDeclared,
    OperationStatus,
    PlaceUse,
)
from keeper.execution.features.declare_operation_place_use import (
    DeclareOperationPlaceUse,
    decide,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 27, 14, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "from": {"type": "string"},
        "to": {"type": "string"},
        "at": {"type": "string"},
        "override": {"type": "object"},
    },
}
_ID = UUID(int=11)


def _operation(
    status: OperationStatus = OperationStatus.ACTIVE,
    place_use: PlaceUse | None = None,
    schema: dict[str, Any] | None = None,
) -> Operation:
    return Operation(
        id=_ID,
        name=OperationName("move"),
        parameters_schema=_SCHEMA if schema is None else schema,
        status=status,
        place_use=place_use,
    )


def _command(places: tuple[str, ...], compute: tuple[str, ...] = ()) -> DeclareOperationPlaceUse:
    return DeclareOperationPlaceUse(
        operation_id=_ID,
        place_use=PlaceUse(place_parameters=places, compute_place_parameters=compute),
    )


def test_declaring_an_undeclared_operation_emits_both_lists_at_the_moment_given() -> None:
    events = decide(_operation(), _command(("from", "to"), ("at",)), now=_NOW)

    assert events == [
        OperationPlaceUseDeclared(
            operation_id=_ID,
            place_parameters=("from", "to"),
            compute_place_parameters=("at",),
            occurred_at=_NOW,
        )
    ]


def test_declaring_that_runs_name_no_place_is_an_answer_and_emits_it() -> None:
    events = decide(_operation(schema={}), _command(()), now=_NOW)

    assert [(e.place_parameters, e.compute_place_parameters) for e in events] == [((), ())]


def test_declaring_an_operation_nobody_defined_is_not_found() -> None:
    with pytest.raises(OperationNotFoundError):
        decide(None, _command(("from",)), now=_NOW)


def test_declaring_a_retired_operation_is_refused_with_its_status() -> None:
    with pytest.raises(OperationPlaceUseCannotBeDeclaredError) as refused:
        decide(_operation(status=OperationStatus.RETIRED), _command(("from",)), now=_NOW)

    assert refused.value.status is OperationStatus.RETIRED
    assert "Retired" in str(refused.value)


def test_declaring_a_second_time_is_refused_even_when_it_agrees_and_carries_the_first() -> None:
    first = PlaceUse(place_parameters=("from", "to"), compute_place_parameters=())

    with pytest.raises(OperationPlaceUseCannotBeDeclaredError) as refused:
        decide(_operation(place_use=first), _command(("from", "to")), now=_NOW)

    assert refused.value.place_use == first
    assert "already declared" in str(refused.value)


def test_a_parameter_the_schema_does_not_declare_is_refused() -> None:
    """A parameter no run can carry would declare places nothing holds, and
    leave the parameter that does hold one reading as naming nothing."""
    with pytest.raises(InvalidOperationPlaceUseError, match="'destination'"):
        decide(_operation(), _command(("from", "destination")), now=_NOW)


def test_a_parameter_the_schema_declares_as_something_other_than_text_is_refused() -> None:
    with pytest.raises(InvalidOperationPlaceUseError, match="text"):
        decide(_operation(), _command((), ("override",)), now=_NOW)


def test_a_schema_with_no_properties_refuses_every_parameter_named() -> None:
    with pytest.raises(InvalidOperationPlaceUseError):
        decide(_operation(schema={"type": "object"}), _command(("at",)), now=_NOW)


@pytest.mark.parametrize(
    ("places", "compute"),
    [(("from", "from"), ()), (("at",), ("at",)), (("",), ())],
    ids=["named-twice-as-a-place", "a-place-and-a-compute-place", "an-empty-name"],
)
def test_a_declaration_that_could_never_be_right_cannot_be_built(
    places: tuple[str, ...], compute: tuple[str, ...]
) -> None:
    with pytest.raises(InvalidOperationPlaceUseError):
        PlaceUse(place_parameters=places, compute_place_parameters=compute)


def test_a_run_names_places_only_in_the_parameters_it_carries() -> None:
    """A collection that does not say where it lands names no place there."""
    declared = PlaceUse(place_parameters=("from", "to"), compute_place_parameters=("at",))

    assert declared.places_in({"from": "19-bm", "to": "alcf", "path": "x/"}) == (
        ("from", "19-bm"),
        ("to", "alcf"),
    )
    assert declared.compute_places_in({"config": "c"}) == ()
    assert declared.compute_places_in({"at": "alcf"}) == (("at", "alcf"),)
