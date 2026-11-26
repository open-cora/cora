"""The decision behind defining a procedure.

Pure, so every case here is a value in and a value or a refusal out. The
one worth reading closely is the parameter check: a procedure may hold
several runs, and a caller told only that one of them is
wrong has to check each by hand.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from keeper.execution.aggregates.operation import (
    Operation,
    OperationCannotBeCitedError,
    OperationName,
    OperationStatus,
)
from keeper.execution.aggregates.procedure import (
    ComposedStep,
    InvalidProcedureBeamlineError,
    InvalidProcedureNameError,
    InvalidProcedureParametersError,
    InvalidProcedureStepsError,
    Procedure,
    ProcedureAlreadyExistsError,
    ProcedureBeamline,
    ProcedureName,
    ProcedureStatus,
    ProcedureStep,
    RunStep,
    SetStep,
)
from keeper.execution.aggregates.setup import Setup, SetupBeamline, SetupName
from keeper.execution.features.define_procedure.command import DefineProcedure
from keeper.execution.features.define_procedure.context import DefineProcedureContext
from keeper.execution.features.define_procedure.decider import decide

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 24, 11, 0, tzinfo=UTC)
_NEW_ID = uuid4()
_PLAN_ID = uuid4()

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


def _context(status: OperationStatus = OperationStatus.ACTIVE) -> DefineProcedureContext:
    return DefineProcedureContext(
        operations={
            _PLAN_ID: Operation(
                id=_PLAN_ID,
                name=OperationName("count"),
                parameters_schema=_SCHEMA,
                status=status,
            )
        },
        setups={},
    )


def _acquire(**overrides: Any) -> RunStep:
    fields: dict[str, Any] = {
        "operation_id": _PLAN_ID,
        "parameters": {"exposure_seconds": 0.2},
        "scopes": ("2bmb:m1",),
    }
    return RunStep(**(fields | overrides))


def _command(
    *steps: ProcedureStep, name: str = "tomography", beamline: str = "  2-bm  "
) -> DefineProcedure:
    return DefineProcedure(
        name=name,
        beamline=beamline,
        steps=steps if steps else (SetStep(record="2bmb:m1", to=1.0),),
    )


def _decide(command: DefineProcedure) -> list[Any]:
    return decide(
        None,
        command,
        context=_context(),
        now=_NOW,
        new_id=_NEW_ID,
        step_ids=[uuid4() for _ in command.steps],
    )


def test_defining_a_procedure_produces_one_genesis_event() -> None:
    (event,) = _decide(_command(SetStep(record="2bmb:m1", to=1.0), _acquire()))
    assert event.procedure_id == _NEW_ID
    assert event.procedure_name == "tomography"
    assert event.occurred_at == _NOW


def test_the_event_carries_every_step_in_the_order_it_was_given() -> None:
    first = SetStep(record="2bmb:m1", to=1.0)
    second = SetStep(record="2bmb:m2", to=2.0)
    (event,) = _decide(_command(first, second, _acquire()))
    assert tuple(composed.step for composed in event.steps) == (first, second, _acquire())


def test_the_beamline_is_trimmed_onto_the_event() -> None:
    (event,) = _decide(_command())
    assert event.beamline == "2-bm"


def test_a_procedure_composed_for_no_beamline_is_refused() -> None:
    """Required, because a dispatch of it could be routed nowhere."""
    with pytest.raises(InvalidProcedureBeamlineError):
        _decide(_command(beamline="   "))


def test_the_name_is_trimmed_onto_the_event() -> None:
    (event,) = _decide(_command(name="  tomography  "))
    assert event.procedure_name == "tomography"


def test_defining_against_an_id_that_already_has_a_history_is_refused() -> None:
    existing = Procedure(
        id=_NEW_ID,
        name=ProcedureName("tomography"),
        beamline=ProcedureBeamline("2-bm"),
        steps=(ComposedStep(id=uuid4(), step=SetStep(record="2bmb:m1", to=1.0)),),
        status=ProcedureStatus.ACTIVE,
    )
    with pytest.raises(ProcedureAlreadyExistsError):
        decide(
            existing,
            _command(),
            context=_context(),
            now=_NOW,
            new_id=_NEW_ID,
            step_ids=[uuid4()],
        )


def test_a_bad_name_is_refused_before_the_steps_are_looked_at() -> None:
    """Cheapest refusal first, and the one a caller can act on fastest."""
    with pytest.raises(InvalidProcedureNameError):
        _decide(_command(_acquire(scopes=()), name="   "))


def test_a_malformed_step_is_refused_before_any_parameters_are_checked() -> None:
    """A schema failure caused by a step that was never storable would
    send its caller to fix the wrong thing."""
    with pytest.raises(InvalidProcedureStepsError):
        _decide(_command(_acquire(scopes=(), parameters={"exposure_seconds": "not a number"})))


def test_an_acquisition_whose_parameters_miss_the_schema_is_refused() -> None:
    with pytest.raises(InvalidProcedureParametersError):
        _decide(_command(_acquire(parameters={"exposure_seconds": "not a number"})))


def test_an_acquisition_supplying_no_parameters_at_all_is_accepted() -> None:
    """The shared validator defers `required` to the point the values are
    acted on, so empty values pass whatever the schema asks for. That is
    the same posture reporting a run takes, and it is asserted here so
    the gap is visible rather than discovered at a beamline."""
    events = _decide(_command(_acquire(parameters={})))
    assert len(events) == 1


def test_the_refusal_names_which_step_failed() -> None:
    """A procedure may hold several runs. A caller told only that one
    of them is wrong has to check each."""
    with pytest.raises(InvalidProcedureParametersError) as caught:
        _decide(
            _command(
                SetStep(record="2bmb:m1", to=1.0),
                _acquire(),
                _acquire(parameters={"exposure_seconds": -1}),
            )
        )
    assert caught.value.index == 2


def _decide_against_a_retired_operation(command: DefineProcedure) -> list[Any]:
    return decide(
        None,
        command,
        context=_context(OperationStatus.RETIRED),
        now=_NOW,
        new_id=_NEW_ID,
        step_ids=[uuid4() for _ in command.steps],
    )


def test_a_run_citing_a_retired_operation_is_refused_with_its_status() -> None:
    """A procedure composed around a routine nothing answers to is one
    whose every dispatch would wait forever."""
    with pytest.raises(OperationCannotBeCitedError) as caught:
        _decide_against_a_retired_operation(_command(SetStep(record="2bmb:m1", to=1.0), _acquire()))
    assert caught.value.operation_id == _PLAN_ID
    assert caught.value.status is OperationStatus.RETIRED


def test_a_retired_operation_is_refused_before_its_parameters_are_checked() -> None:
    """Values checked against a routine nothing answers to tell the caller
    nothing worth fixing, so the retirement is what it hears about."""
    with pytest.raises(OperationCannotBeCitedError):
        _decide_against_a_retired_operation(
            _command(_acquire(parameters={"exposure_seconds": "not a number"}))
        )


def test_a_procedure_of_sets_alone_needs_no_operations_at_all() -> None:
    """The context is empty and nothing looks in it, because a set cites
    nothing."""
    events = decide(
        None,
        _command(SetStep(record="2bmb:m1", to=1.0)),
        context=DefineProcedureContext(operations={}, setups={}),
        now=_NOW,
        new_id=_NEW_ID,
        step_ids=[uuid4()],
    )
    assert len(events) == 1


def test_every_step_is_named_with_the_id_it_was_given_in_order() -> None:
    command = _command(SetStep(record="2bmb:m1", to=1.0), _acquire())
    step_ids = [uuid4(), uuid4()]
    (event,) = decide(
        None,
        command,
        context=_context(),
        now=_NOW,
        new_id=_NEW_ID,
        step_ids=step_ids,
    )
    assert [composed.id for composed in event.steps] == step_ids


def test_two_steps_that_are_identical_are_still_named_apart() -> None:
    """What the ids buy over a position: a procedure may repeat a step,
    and an execution of it has to be able to say which one it means."""
    same = SetStep(record="2bmb:m1", to=1.0)
    (event,) = _decide(_command(same, same))
    first, second = event.steps
    assert first.step == second.step
    assert first.id != second.id


def test_a_definition_given_the_wrong_number_of_step_ids_is_a_caller_bug() -> None:
    with pytest.raises(ValueError, match="one id per step"):
        decide(
            None,
            _command(SetStep(record="2bmb:m1", to=1.0), _acquire()),
            context=_context(),
            now=_NOW,
            new_id=_NEW_ID,
            step_ids=[uuid4()],
        )


def test_a_run_that_says_it_drives_no_device_is_stored_without_scopes() -> None:
    """Work that happens at another facility has no honest scope to name.

    The rule this relaxes was about a step somebody forgot to describe.
    A transfer drives nothing, and every scope it could name would be a
    fiction the record keeps for good, retired or not.
    """
    (event,) = _decide(_command(_acquire(scopes=(), drives_no_device=True)))

    (step,) = event.steps
    assert step.step.scopes == ()
    assert step.step.drives_no_device is True


def test_a_run_declaring_no_devices_and_not_saying_so_is_still_refused() -> None:
    """Silence is what forgetting looks like, and stays an error."""
    with pytest.raises(InvalidProcedureStepsError, match="declaring no devices"):
        _decide(_command(_acquire(scopes=())))


def test_a_run_that_names_devices_and_claims_to_drive_none_is_refused() -> None:
    """Two halves that contradict, and this system will not pick one."""
    with pytest.raises(InvalidProcedureStepsError, match="drives none"):
        _decide(_command(_acquire(scopes=("2bmb:m1",), drives_no_device=True)))


_PROCESS_ID = uuid4()

_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"config": {"type": "string"}, "override": {"type": "object"}},
}

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "rotation-axis": {"type": "number"},
        "binning": {"type": "integer", "enum": [1, 2, 4]},
    },
}


def _held_setup(*, beamline: str = "2-bm") -> Setup:
    return Setup(
        id=uuid4(),
        beamline=SetupBeamline(beamline),
        operation_id=_PROCESS_ID,
        name=SetupName("tomo-default"),
        settings={"rotation-axis": 1630.0, "binning": 2},
        settings_schema=_SETTINGS_SCHEMA,
        revision=1,
    )


def _process(**parameters: Any) -> RunStep:
    return RunStep(operation_id=_PROCESS_ID, parameters=parameters, scopes=("2bmb:det:",))


def _decide_with_setups(command: DefineProcedure, *setups: Setup) -> list[Any]:
    return decide(
        None,
        command,
        context=DefineProcedureContext(
            operations={
                _PLAN_ID: _context().operations[_PLAN_ID],
                _PROCESS_ID: Operation(
                    id=_PROCESS_ID,
                    name=OperationName("process"),
                    parameters_schema=_PROCESS_SCHEMA,
                    status=OperationStatus.ACTIVE,
                ),
            },
            setups={(setup.operation_id, setup.name): setup for setup in setups},
        ),
        now=_NOW,
        new_id=_NEW_ID,
        step_ids=[uuid4() for _ in command.steps],
    )


def test_a_run_naming_a_setup_the_beamline_holds_is_defined() -> None:
    step = _process(config="tomo-default", override={"binning": 4})

    (event,) = _decide_with_setups(_command(step), _held_setup())

    assert tuple(composed.step for composed in event.steps) == (step,)


def test_a_run_naming_a_setup_the_beamline_does_not_hold_is_refused_with_both_names() -> None:
    with pytest.raises(InvalidProcedureParametersError) as caught:
        _decide_with_setups(_command(_process(config="flat-field")), _held_setup())

    assert caught.value.index == 0
    assert "flat-field" in caught.value.reason
    assert "2-bm" in caught.value.reason


def test_a_run_of_a_setup_taking_operation_that_names_none_is_refused() -> None:
    """Empty parameters pass any operation schema, because `required` is
    deferred, and still name no setup, so this is the one empty run refused."""
    with pytest.raises(InvalidProcedureParametersError) as caught:
        _decide_with_setups(_command(_process()), _held_setup())

    assert str(_PROCESS_ID) in caught.value.reason


def test_an_override_naming_a_setting_the_setup_does_not_describe_is_refused() -> None:
    with pytest.raises(InvalidProcedureParametersError) as caught:
        _decide_with_setups(
            _command(_process(config="tomo-default", override={"dark-fields": 10})),
            _held_setup(),
        )

    assert "dark-fields" in caught.value.reason
    assert "tomo-default" in caught.value.reason


def test_an_override_value_the_setups_description_refuses_is_refused() -> None:
    with pytest.raises(InvalidProcedureParametersError) as caught:
        _decide_with_setups(
            _command(_process(config="tomo-default", override={"binning": 3})), _held_setup()
        )

    assert "binning" in caught.value.reason


def test_a_setup_held_for_another_operation_is_not_the_one_a_run_names() -> None:
    """Keyed by operation as well as name, so two operations at one
    beamline can each hold a setup called the same thing."""
    held_for_the_other = replace(_held_setup(), operation_id=_PLAN_ID)
    with pytest.raises(InvalidProcedureParametersError):
        _decide_with_setups(_command(_process(config="tomo-default")), held_for_the_other)


def test_a_run_of_an_operation_that_takes_no_setup_is_not_asked_about_one() -> None:
    """The plain operation's runs pass with no setup in the context at all."""
    events = _decide_with_setups(_command(_acquire()))

    assert len(events) == 1


def test_a_setup_refusal_names_the_step_among_several_runs() -> None:
    with pytest.raises(InvalidProcedureParametersError) as caught:
        _decide_with_setups(
            _command(
                _process(config="tomo-default"),
                _acquire(),
                _process(config="tomo-default", override={"binning": 3}),
            ),
            _held_setup(),
        )

    assert caught.value.index == 2


def test_a_run_failing_its_operations_schema_hears_that_before_anything_about_a_setup() -> None:
    """An override that is not even the object the operation declares is
    that refusal, not one about the setup it was meant for."""
    with pytest.raises(InvalidProcedureParametersError) as caught:
        _decide_with_setups(_command(_process(config="flat-field", override=[1, 2])))

    assert "satisfy the operation" in caught.value.reason
