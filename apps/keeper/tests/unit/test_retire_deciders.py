"""The two retirement deciders, an operation's and a procedure's.

One file for both, because they are the same decision about two
aggregates: refuse an absent record, refuse a second retirement, and
otherwise write one event stamped with the moment passed in.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.operation import (
    Operation,
    OperationCannotBeRetiredError,
    OperationName,
    OperationNotFoundError,
    OperationRetired,
    OperationStatus,
)
from keeper.execution.aggregates.procedure import (
    ComposedStep,
    Procedure,
    ProcedureBeamline,
    ProcedureCannotBeRetiredError,
    ProcedureName,
    ProcedureNotFoundError,
    ProcedureRetired,
    ProcedureStatus,
    SetStep,
)
from keeper.execution.features.retire_operation import RetireOperation
from keeper.execution.features.retire_operation import decide as decide_operation
from keeper.execution.features.retire_procedure import RetireProcedure
from keeper.execution.features.retire_procedure import decide as decide_procedure

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_ID = UUID(int=3)


def _operation(status: OperationStatus) -> Operation:
    return Operation(
        id=_ID, name=OperationName("transfer"), parameters_schema=_SCHEMA, status=status
    )


def _procedure(status: ProcedureStatus) -> Procedure:
    return Procedure(
        id=_ID,
        name=ProcedureName("Move a dataset"),
        beamline=ProcedureBeamline("19-bm"),
        steps=(ComposedStep(id=uuid4(), step=SetStep(record="19bm:m1", to=0.0)),),
        status=status,
    )


def test_retiring_an_active_operation_emits_one_event_at_the_moment_given() -> None:
    events = decide_operation(
        _operation(OperationStatus.ACTIVE), RetireOperation(operation_id=_ID), now=_NOW
    )

    assert events == [OperationRetired(operation_id=_ID, occurred_at=_NOW)]


def test_retiring_an_operation_twice_is_refused_with_its_status() -> None:
    with pytest.raises(OperationCannotBeRetiredError) as caught:
        decide_operation(
            _operation(OperationStatus.RETIRED), RetireOperation(operation_id=_ID), now=_NOW
        )

    assert caught.value.status is OperationStatus.RETIRED


def test_retiring_an_operation_nobody_defined_is_refused() -> None:
    with pytest.raises(OperationNotFoundError):
        decide_operation(None, RetireOperation(operation_id=_ID), now=_NOW)


def test_retiring_an_active_procedure_emits_one_event_at_the_moment_given() -> None:
    events = decide_procedure(
        _procedure(ProcedureStatus.ACTIVE), RetireProcedure(procedure_id=_ID), now=_NOW
    )

    assert events == [ProcedureRetired(procedure_id=_ID, occurred_at=_NOW)]


def test_retiring_a_procedure_twice_is_refused_with_its_status() -> None:
    with pytest.raises(ProcedureCannotBeRetiredError) as caught:
        decide_procedure(
            _procedure(ProcedureStatus.RETIRED), RetireProcedure(procedure_id=_ID), now=_NOW
        )

    assert caught.value.status is ProcedureStatus.RETIRED


def test_retiring_a_procedure_nobody_composed_is_refused() -> None:
    with pytest.raises(ProcedureNotFoundError):
        decide_procedure(None, RetireProcedure(procedure_id=_ID), now=_NOW)
