"""The decision: what declaring an operation's place use produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime
from typing import Any, cast

from keeper.execution.aggregates.operation import (
    InvalidOperationPlaceUseError,
    Operation,
    OperationNotFoundError,
    OperationPlaceUseCannotBeDeclaredError,
    OperationPlaceUseDeclared,
    PlaceUse,
)
from keeper.execution.features.declare_operation_place_use.command import (
    DeclareOperationPlaceUse,
)


def decide(
    state: Operation | None,
    command: DeclareOperationPlaceUse,
    *,
    now: datetime,
) -> list[OperationPlaceUseDeclared]:
    """Decide the events produced by declaring an operation's place use.

    Invariants:
      - State must not be None, or no such operation was defined
        -> OperationNotFoundError
      - The operation must not be retired
        -> OperationPlaceUseCannotBeDeclaredError
      - Its place use must not be declared already, whatever it said
        -> OperationPlaceUseCannotBeDeclaredError
      - Every parameter named must be one the operation's schema declares,
        as text -> InvalidOperationPlaceUseError

    Retirement is asked first, and a second declaration is refused even
    when it agrees with the first, for the reasons the device use decider
    gives.

    The schema check is what keeps a declaration honest about the routine
    it is made for. A parameter the schema does not declare is one no run
    can carry, so naming it would declare places nothing will ever hold,
    and the parameter that does hold one would read as naming nothing. A
    parameter declared as something other than text cannot hold a place's
    name at all.
    """
    if state is None:
        raise OperationNotFoundError(command.operation_id)
    if state.is_retired or state.place_use is not None:
        raise OperationPlaceUseCannotBeDeclaredError(
            state.id, status=state.status, place_use=state.place_use
        )
    _refuse_what_the_schema_does_not_take(command.place_use, state.parameters_schema)
    return [
        OperationPlaceUseDeclared(
            operation_id=command.operation_id,
            place_parameters=command.place_use.place_parameters,
            compute_place_parameters=command.place_use.compute_place_parameters,
            occurred_at=now,
        )
    ]


def _refuse_what_the_schema_does_not_take(place_use: PlaceUse, schema: dict[str, Any]) -> None:
    """Raise unless every parameter named is a text property of the schema."""
    raw = schema.get("properties")
    properties = cast("dict[str, object]", raw) if isinstance(raw, dict) else {}
    for parameter in (*place_use.place_parameters, *place_use.compute_place_parameters):
        declared = properties.get(parameter)
        if not isinstance(declared, dict):
            msg = f"{parameter!r} is not a parameter this operation's schema declares"
            raise InvalidOperationPlaceUseError(msg)
        if cast("dict[str, object]", declared).get("type") != "string":
            msg = f"{parameter!r} is not declared as text, and a place is named by text"
            raise InvalidOperationPlaceUseError(msg)


__all__ = ["decide"]
