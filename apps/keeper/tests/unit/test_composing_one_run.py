"""The seam two contexts reach for to dispatch one run of one operation.

Adoption and a pursuit's advance both call this, so it is tested here
rather than only through whichever of them happens to exercise a branch.
That is the difference a second caller makes: a helper with one consumer
is covered by that consumer's tests, and a helper with two is a thing in
its own right that either could break for the other.

Nothing here touches a store. The function is pure over its arguments,
including the two callables, which is what makes every assertion below a
statement about the appends rather than about a database.

What is deliberately not retested is what Execution's own deciders
refuse. A procedure with no steps and a parameter set that fails its
operation's schema are checked where those deciders are, and repeating them
here would pin this module to refusals it does not make.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.execution import EXECUTION_STREAM_TYPE
from keeper.execution.aggregates.operation import (
    Operation,
    OperationCannotBeCitedError,
    OperationName,
    OperationStatus,
)
from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    InvalidProcedureParametersError,
)
from keeper.execution.aggregates.setup import Setup, SetupBeamline, SetupName
from keeper.execution.composing import compose_one_run
from keeper.infrastructure.ports.event_store import NewEvent, StreamAppend
from keeper.infrastructure.slices.envelope import to_new_event

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_CALLER = "SomebodysCommand"


def _an_operation(status: OperationStatus = OperationStatus.ACTIVE) -> Operation:
    return Operation(
        id=uuid4(), name=OperationName("count"), parameters_schema=_SCHEMA, status=status
    )


class _CountingIds:
    """Hands out ids in a fixed order, so a run can be compared with itself."""

    def __init__(self) -> None:
        self.given: list[UUID] = []

    def __call__(self) -> UUID:
        minted = UUID(int=len(self.given) + 1)
        self.given.append(minted)
        return minted


def _envelope(event_type: str, payload: dict[str, Any], occurred_at: datetime) -> NewEvent:
    """A caller's own maker, stamping a caller's own command name."""
    return to_new_event(
        event_type=event_type,
        payload=payload,
        occurred_at=occurred_at,
        event_id=uuid4(),
        command_name=_CALLER,
        correlation_id=uuid4(),
        principal_id=uuid4(),
    )


def _composed(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "operation": _an_operation(),
        "parameters": {"exposure_time_s": 2},
        "beamline": "2-bm",
        "scopes": ("2bmb:det:",),
        "drives_no_device": False,
        "setups": {},
        "now": _WHEN,
        "new_id": _CountingIds(),
        "envelope": _envelope,
    }
    fields.update(overrides)
    return compose_one_run(**fields)


def _every_event(appends: Sequence[StreamAppend]) -> list[NewEvent]:
    return [event for append in appends for event in append.events]


def test_composing_produces_a_procedure_then_an_execution() -> None:
    """The order is the order a reader of the log wants: the routine is
    composed before anything traverses it."""
    run = _composed()

    assert [append.stream_type for append in run.appends] == [
        PROCEDURE_STREAM_TYPE,
        EXECUTION_STREAM_TYPE,
    ]


def test_both_streams_are_new_so_neither_can_collide_with_anything() -> None:
    run = _composed()

    assert [append.expected_version for append in run.appends] == [0, 0]


def test_the_execution_append_is_the_execution_that_comes_back() -> None:
    run = _composed()

    execution_append = run.appends[1]
    assert execution_append.stream_id == run.execution_id


def test_the_execution_cites_the_procedure_composed_beside_it() -> None:
    """The dispatch decider takes the procedure as a value, folded out of
    an event that is in no store yet, so this is where that wiring is
    checked. The execution names the procedure and each of its steps names
    the definition step it came from, and neither could be filled in
    without the fold."""
    run = _composed()

    procedure = run.appends[0].events[0].payload
    execution = run.appends[1].events[0].payload
    assert execution["procedure_id"] == str(run.appends[0].stream_id)
    assert execution["steps"][0]["procedure_step_id"] == procedure["steps"][0]["id"]


def test_the_step_handed_back_is_the_dispatched_one_and_not_the_composed_one() -> None:
    """Two step ids are minted and they are different things. A record
    citing this run points at the step inside the execution, not at the
    one inside the definition it was composed from."""
    run = _composed()

    dispatched = run.appends[1].events[0].payload["steps"]
    assert [step["id"] for step in dispatched] == [str(run.step_id)]
    composed = run.appends[0].events[0].payload["steps"]
    assert [step["id"] for step in composed] != [str(run.step_id)]


def test_the_procedure_is_named_for_the_plan_and_runs_it() -> None:
    operation = _an_operation()

    run = _composed(operation=operation)

    defined = run.appends[0].events[0].payload
    assert defined["procedure_name"] == operation.name.value
    assert defined["steps"][0]["operation_id"] == str(operation.id)


def test_the_beamline_and_the_scopes_are_the_callers_and_nothing_else() -> None:
    """The two safety-bearing facts. Neither is inferred from the operation, the
    parameters or anything this module could reach."""
    run = _composed(beamline="7-bm", scopes=("7bma:det:", "7bma:m1"))

    defined = run.appends[0].events[0].payload
    assert defined["beamline"] == "7-bm"
    assert defined["steps"][0]["scopes"] == ["7bma:det:", "7bma:m1"]


def test_every_event_is_stamped_with_the_callers_command_rather_than_this_ones() -> None:
    """The reason the envelope maker is an argument. These events were
    produced by whatever command the caller is running, and a module that
    stamped its own name would leave the log saying a procedure was
    composed by a command nobody issued."""
    run = _composed()

    assert {event.metadata["command"] for event in _every_event(run.appends)} == {_CALLER}


def test_every_event_is_stamped_with_the_moment_the_caller_passed() -> None:
    run = _composed()

    assert {event.occurred_at for event in _every_event(run.appends)} == {_WHEN}


def test_the_parameters_reach_the_acquisition_as_they_were_given() -> None:
    run = _composed(parameters={"exposure_time_s": 4, "frames": 10})

    assert run.appends[0].events[0].payload["steps"][0]["parameters"] == {
        "exposure_time_s": 4,
        "frames": 10,
    }


def test_the_same_inputs_and_the_same_generator_compose_the_same_run() -> None:
    """Ids arrive from the caller's port rather than from anything reached
    for here, so a decision is reproducible on replay."""
    operation = _an_operation()

    first = _composed(operation=operation, new_id=_CountingIds())
    second = _composed(operation=operation, new_id=_CountingIds())

    assert (first.execution_id, first.step_id) == (second.execution_id, second.step_id)
    assert [append.stream_id for append in first.appends] == [
        append.stream_id for append in second.appends
    ]


def test_composing_around_a_retired_operation_is_refused_and_hands_back_nothing() -> None:
    """The path a proposal's adoption takes, which defines and dispatches in
    one go without passing through either slice's handler. The refusal
    has to hold here too, or adopting old advice would dispatch a run
    nothing answers to."""
    with pytest.raises(OperationCannotBeCitedError):
        _composed(operation=_an_operation(OperationStatus.RETIRED))


def test_four_ids_are_minted_and_no_more() -> None:
    """A procedure, its composed step, an execution and its dispatched
    step. A fifth would mean something is being created that nothing
    named."""
    ids = _CountingIds()

    _composed(new_id=ids)

    assert len(ids.given) == 4


_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"config": {"type": "string"}, "override": {"type": "object"}},
}


def _a_process() -> Operation:
    return Operation(
        id=uuid4(),
        name=OperationName("process"),
        parameters_schema=_PROCESS_SCHEMA,
        status=OperationStatus.ACTIVE,
    )


def _held_for(operation: Operation, *, revision: int = 1) -> Setup:
    return Setup(
        id=uuid4(),
        beamline=SetupBeamline("2-bm"),
        operation_id=operation.id,
        name=SetupName("tomo-default"),
        settings={"binning": 2},
        settings_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"binning": {"type": "integer"}},
        },
        revision=revision,
    )


def test_a_run_naming_a_held_setup_is_pinned_in_the_execution_append() -> None:
    """Pinned to the dispatched step, in the same append as the genesis, so a
    caller committing the appends commits the pin with them."""
    operation = _a_process()
    setup = _held_for(operation, revision=2)

    run = _composed(
        operation=operation,
        parameters={"config": "tomo-default", "override": {"binning": 4}},
        setups={(operation.id, setup.name): setup},
    )

    genesis, pinned = run.appends[1].events
    assert genesis.event_type == "ExecutionDispatched"
    assert pinned.event_type == "ExecutionSetupsPinned"
    assert pinned.payload["pins"] == [
        {"step_id": str(run.step_id), "setup_id": str(setup.id), "revision": 2}
    ]


def test_a_run_of_an_operation_taking_no_setup_dispatches_the_genesis_alone() -> None:
    run = _composed()

    assert [event.event_type for event in run.appends[1].events] == ["ExecutionDispatched"]


def test_a_setup_the_beamline_does_not_hold_is_refused_as_the_runs_parameters() -> None:
    """Both decisions here check the setup, and the definition asks first, so
    a caller of this function hears the refusal a procedure's parameters get
    rather than the one a dispatch gives. Adoption's status follows from
    that, which is why it is pinned here rather than left to the deciders."""
    operation = _a_process()

    with pytest.raises(InvalidProcedureParametersError, match="tomo-default"):
        _composed(
            operation=operation,
            parameters={"config": "tomo-default"},
            setups={},
        )
