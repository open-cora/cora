"""The composing seam given a sequence of runs, and an operation's declared device use.

`test_composing_one_run.py` pins that one run composes exactly what it did
before the seam could compose several. This file holds what is new: one
procedure and one execution for the whole sequence, the order kept, and
the rule by which each operation's declared device use decides what its
run may claim.

Nothing here touches a store, for the reason the sibling file gives.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.execution.aggregates.operation import (
    Operation,
    OperationCannotBeCitedError,
    OperationCannotBeComposedError,
    OperationName,
    OperationStatus,
)
from keeper.execution.aggregates.procedure import (
    PROCEDURE_NAME_MAX_LENGTH,
    InvalidProcedureParametersError,
    InvalidProcedureStepsError,
)
from keeper.execution.aggregates.setup import Setup, SetupBeamline, SetupName
from keeper.execution.composing import ComposedRuns, compose_runs
from keeper.infrastructure.ports.event_store import NewEvent
from keeper.infrastructure.slices.envelope import to_new_event

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 11, 27, 9, 0, tzinfo=UTC)
_SCHEMA: dict[str, Any] = {"$schema": "https://json-schema.org/draft/2020-12/schema"}
_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"config": {"type": "string"}, "override": {"type": "object"}},
}


def _an_operation(
    name: str,
    *,
    drives_devices: bool | None,
    status: OperationStatus = OperationStatus.ACTIVE,
    schema: dict[str, Any] | None = None,
) -> Operation:
    return Operation(
        id=uuid4(),
        name=OperationName(name),
        parameters_schema=schema if schema is not None else _SCHEMA,
        status=status,
        drives_devices=drives_devices,
    )


class _CountingIds:
    """Hands out ids in a fixed order, so a composition can be compared with itself."""

    def __init__(self) -> None:
        self.given: list[UUID] = []

    def __call__(self) -> UUID:
        minted = UUID(int=len(self.given) + 1)
        self.given.append(minted)
        return minted


def _envelope(event_type: str, payload: dict[str, Any], occurred_at: datetime) -> NewEvent:
    return to_new_event(
        event_type=event_type,
        payload=payload,
        occurred_at=occurred_at,
        event_id=uuid4(),
        command_name="SomebodysCommand",
        correlation_id=uuid4(),
        principal_id=uuid4(),
    )


def _composed(
    runs: list[tuple[Operation, dict[str, Any]]],
    *,
    scopes: tuple[str, ...] = ("2bmb:det:",),
    drives_no_device: bool = False,
    setups: dict[tuple[UUID, SetupName], Setup] | None = None,
    new_id: _CountingIds | None = None,
) -> ComposedRuns:
    return compose_runs(
        runs=runs,
        beamline="2-bm",
        scopes=scopes,
        drives_no_device=drives_no_device,
        setups=setups if setups is not None else {},
        now=_WHEN,
        new_id=new_id if new_id is not None else _CountingIds(),
        envelope=_envelope,
    )


def _defined_steps(composed: ComposedRuns) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = composed.appends[0].events[0].payload["steps"]
    return steps


def _a_plan() -> list[tuple[Operation, dict[str, Any]]]:
    """A collection here, a transfer and a reconstruction elsewhere, and the result back."""
    collect = _an_operation("collect", drives_devices=True)
    move = _an_operation("move", drives_devices=False)
    process = _an_operation("process", drives_devices=False)
    return [
        (collect, {"exposure_time_s": 2}),
        (move, {"to": "alcf"}),
        (process, {"algorithm": "gridrec"}),
        (move, {"to": "aps"}),
    ]


def test_several_runs_compose_one_procedure_and_one_execution() -> None:
    composed = _composed(_a_plan())

    assert [append.expected_version for append in composed.appends] == [0, 0]
    assert len(composed.appends) == 2


def test_each_run_is_one_step_in_the_order_the_runs_were_given() -> None:
    runs = _a_plan()

    composed = _composed(runs)

    assert [(step["operation_id"], step["parameters"]) for step in _defined_steps(composed)] == [
        (str(operation.id), parameters) for operation, parameters in runs
    ]


def test_the_step_ids_handed_back_are_the_dispatched_steps_in_order() -> None:
    composed = _composed(_a_plan())

    dispatched = composed.appends[1].events[0].payload["steps"]
    assert [step["id"] for step in dispatched] == [str(step_id) for step_id in composed.step_ids]
    assert len(composed.step_ids) == 4


def test_each_dispatched_step_cites_the_composed_step_in_the_same_place() -> None:
    composed = _composed(_a_plan())

    defined = [step["id"] for step in _defined_steps(composed)]
    dispatched = composed.appends[1].events[0].payload["steps"]
    assert [step["procedure_step_id"] for step in dispatched] == defined


def test_the_ids_are_minted_procedure_composed_steps_execution_then_dispatched_steps() -> None:
    """One run minting exactly the four it always did depends on this order."""
    ids = _CountingIds()

    composed = _composed(_a_plan(), new_id=ids)

    assert len(ids.given) == 2 + 2 * 4
    assert composed.appends[0].stream_id == ids.given[0]
    assert [step["id"] for step in _defined_steps(composed)] == [str(i) for i in ids.given[1:5]]
    assert composed.execution_id == ids.given[5]
    assert list(composed.step_ids) == ids.given[6:]


def test_a_procedure_of_several_runs_is_named_for_its_operations_in_order() -> None:
    composed = _composed(_a_plan())

    assert composed.appends[0].events[0].payload["procedure_name"] == (
        "collect, move, process, move"
    )


def test_a_name_too_long_for_the_bound_is_cut_short_rather_than_refused() -> None:
    """A label is the wrong thing to refuse work over."""
    long_name = "x" * 120
    first = _an_operation(long_name, drives_devices=False)
    second = _an_operation(long_name, drives_devices=False)

    composed = _composed([(first, {}), (second, {})])

    name = composed.appends[0].events[0].payload["procedure_name"]
    assert len(name) <= PROCEDURE_NAME_MAX_LENGTH
    assert name.startswith(long_name + ", ")
    assert name.endswith("...")


def test_a_run_of_an_operation_declared_to_drive_nothing_claims_no_devices() -> None:
    """Whatever the bound said: the facility's declaration decides."""
    transfer = _an_operation("move", drives_devices=False)

    composed = _composed([(transfer, {})], scopes=("2bmb:det:", "2bmb:m1"))

    (step,) = _defined_steps(composed)
    assert (step["scopes"], step["drives_no_device"]) == ([], True)


def test_a_run_of_an_operation_declared_to_drive_devices_takes_the_bounds_scopes() -> None:
    collect = _an_operation("collect", drives_devices=True)
    move = _an_operation("move", drives_devices=False)

    composed = _composed([(collect, {}), (move, {})], scopes=("2bmb:det:", "2bmb:m1"))

    assert [(step["scopes"], step["drives_no_device"]) for step in _defined_steps(composed)] == [
        (["2bmb:det:", "2bmb:m1"], False),
        ([], True),
    ]


def test_a_bound_naming_devices_and_saying_the_runs_drive_none_is_refused_even_when_none_do() -> (
    None
):
    """A caller contradicting itself, refused before any run is read for it."""
    move = _an_operation("move", drives_devices=False)
    ids = _CountingIds()

    with pytest.raises(InvalidProcedureStepsError, match="will not pick which"):
        _composed([(move, {})], scopes=("2bmb:det:",), drives_no_device=True, new_id=ids)

    assert ids.given == [], "a refusal comes before anything is minted"


def test_a_composition_of_several_runs_refuses_an_undeclared_operation_and_names_it() -> None:
    collect = _an_operation("collect", drives_devices=True)
    undeclared = _an_operation("move", drives_devices=None)
    ids = _CountingIds()

    with pytest.raises(OperationCannotBeComposedError, match=str(undeclared.id)) as caught:
        _composed([(collect, {}), (undeclared, {})], new_id=ids)

    assert (caught.value.operation_id, caught.value.index) == (undeclared.id, 1)
    assert caught.value.drives_devices is None
    assert ids.given == [], "a refusal comes before anything is minted"


def test_one_run_of_an_undeclared_operation_takes_the_bound_exactly() -> None:
    """Today's behaviour, both halves of the bound: scopes, or a declaration."""
    undeclared = _an_operation("count", drives_devices=None)

    with_scopes = _composed([(undeclared, {})], scopes=("2bmb:det:",))
    driving_nothing = _composed([(undeclared, {})], scopes=(), drives_no_device=True)

    assert [
        (step["scopes"], step["drives_no_device"])
        for composed in (with_scopes, driving_nothing)
        for step in _defined_steps(composed)
    ] == [(["2bmb:det:"], False), ([], True)]


def test_a_bound_saying_nothing_is_driven_is_refused_for_an_operation_declared_to_drive() -> None:
    collect = _an_operation("collect", drives_devices=True)

    with pytest.raises(OperationCannotBeComposedError, match="Name the devices") as caught:
        _composed([(collect, {})], scopes=(), drives_no_device=True)

    assert (caught.value.operation_id, caught.value.drives_devices) == (collect.id, True)


def test_a_bound_saying_nothing_is_driven_suits_a_plan_whose_runs_all_drive_nothing() -> None:
    move = _an_operation("move", drives_devices=False)
    process = _an_operation("process", drives_devices=False)

    composed = _composed([(move, {}), (process, {})], scopes=(), drives_no_device=True)

    assert {step["drives_no_device"] for step in _defined_steps(composed)} == {True}


def test_a_run_that_drives_devices_with_no_scopes_and_no_declaration_is_still_refused() -> None:
    """The step's own rule is unchanged: silence about devices is refused."""
    collect = _an_operation("collect", drives_devices=True)
    move = _an_operation("move", drives_devices=False)

    with pytest.raises(InvalidProcedureStepsError, match="Step 0"):
        _composed([(collect, {}), (move, {})], scopes=())


def test_a_retired_operation_is_refused_before_its_device_use_is_asked_about() -> None:
    """Its device use can no longer be declared, so that refusal would send the
    caller after a fix that cannot be made."""
    collect = _an_operation("collect", drives_devices=True)
    retired = _an_operation("move", drives_devices=None, status=OperationStatus.RETIRED)

    with pytest.raises(OperationCannotBeCitedError) as caught:
        _composed([(retired, {}), (collect, {})])

    assert caught.value.operation_id == retired.id


def test_every_run_naming_a_setup_is_pinned_to_its_own_step() -> None:
    process = _an_operation("process", drives_devices=False, schema=_PROCESS_SCHEMA)
    setup = Setup(
        id=uuid4(),
        beamline=SetupBeamline("2-bm"),
        operation_id=process.id,
        name=SetupName("tomo-default"),
        settings={"binning": 2},
        settings_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"binning": {"type": "integer"}},
        },
        revision=3,
    )
    collect = _an_operation("collect", drives_devices=True)

    composed = _composed(
        [
            (collect, {}),
            (process, {"config": "tomo-default"}),
            (process, {"config": "tomo-default", "override": {"binning": 4}}),
        ],
        setups={(process.id, setup.name): setup},
    )

    _genesis, pinned = composed.appends[1].events
    assert pinned.payload["pins"] == [
        {"step_id": str(composed.step_ids[1]), "setup_id": str(setup.id), "revision": 3},
        {"step_id": str(composed.step_ids[2]), "setup_id": str(setup.id), "revision": 3},
    ]


def test_one_run_naming_a_setup_the_beamline_does_not_hold_refuses_the_whole_sequence() -> None:
    process = _an_operation("process", drives_devices=False, schema=_PROCESS_SCHEMA)
    collect = _an_operation("collect", drives_devices=True)

    with pytest.raises(InvalidProcedureParametersError, match="Step 1"):
        _composed([(collect, {}), (process, {"config": "tomo-default"})], setups={})
