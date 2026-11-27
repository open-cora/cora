"""The decision: what defining a procedure produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from keeper.execution.aggregates.operation import OperationCannotBeCitedError
from keeper.execution.aggregates.procedure import (
    ComposedStep,
    InvalidProcedureParametersError,
    Procedure,
    ProcedureAlreadyExistsError,
    ProcedureBeamline,
    ProcedureDefined,
    ProcedureName,
    RunStep,
    validated_steps,
)
from keeper.execution.aggregates.setup import can_take_a_setup, setup_refusal
from keeper.execution.features.define_procedure.command import DefineProcedure
from keeper.execution.features.define_procedure.context import DefineProcedureContext
from keeper.shared.json_schema.validation import validate_values_against_schema


class _ParametersRejectedError(ValueError):
    """What the shared validator raises here, before the step is named.

    The validator constructs its error class from a reason alone, and the
    refusal this slice publishes also carries which step the reason came
    from. So the reason is caught in this private shape and re-raised in
    the public one, one line below, rather than leaving a caller with a
    procedure told only that one of its runs is wrong.
    """


def decide(
    state: Procedure | None,
    command: DefineProcedure,
    *,
    context: DefineProcedureContext,
    now: datetime,
    new_id: UUID,
    step_ids: Sequence[UUID],
) -> list[ProcedureDefined]:
    """Decide the events produced by defining a procedure.

    Invariants:
      - State must be None, or the id already has a history
        -> ProcedureAlreadyExistsError
      - The name must be non-empty and within the length bound
        -> InvalidProcedureNameError
      - The beamline must be non-empty and within its length bound
        -> InvalidProcedureBeamlineError
      - The step list must be non-empty, within the length bound, and
        every step storable -> InvalidProcedureStepsError
      - No run may cite an operation that has been retired
        -> OperationCannotBeCitedError
      - Every run's parameters must satisfy the schema its operation
        declares -> InvalidProcedureParametersError
      - A run of an operation that takes a setup must name, in its
        config, a setup held for that operation at the procedure's
        beamline, and its override may hold only settings that setup
        describes, each satisfying its description
        -> InvalidProcedureParametersError

    The order is deliberate and runs cheapest first. The stream check
    comes first because it is about whether this command may be answered
    at all. The name and the beamline are next because they are one
    comparison each. The step list
    is checked whole before any parameters are, so a caller who sent a
    malformed step hears about that rather than about a schema failure
    caused by it. A retired operation is refused before its parameters
    are read, because values checked against a routine nothing answers to
    tell the caller nothing worth fixing. The setups are asked about last,
    once every run's parameters have satisfied their operation: an
    override that is not even the shape the operation declares is that
    refusal, not a refusal about the setup it was meant for.

    That a cited operation exists is NOT checked here. It needs a store, and
    the handler has already refused a procedure citing one that does not.
    Whether it is retired is checked here, because the handler hands the
    operation across whole and its status is part of it. That is also what
    makes the refusal hold for `compose_runs`, which calls this function
    without going through the handler.

    A run supplying no parameters at all is accepted whatever
    its operation requires, because the shared validator defers `required` to
    the point the values are acted on. Reporting a step's run has the
    same gap and for the same reason: the check here is carrier-side,
    and the thing finally resolving the values is the engine. The one
    exception is an operation that takes a setup, because a run of it has
    to name one and an empty set of parameters names none.

    Which setup a name means is NOT read here, for the reason an operation
    is not: it needs a store. The handler resolves each run's setup at the
    procedure's beamline and hands the setups across, so a miss is a
    refusal with an index rather than a missing record, and the check holds
    for `compose_runs` too, which calls this function with setups its
    own caller resolved.

    `step_ids` arrives minted rather than being made here, for the reason
    `new_id` does: this function is pure, and the ids have to be on the
    genesis payload so the fold names the same steps on every replay.
    One per step, in order. A list of the wrong length is a caller bug
    rather than a domain refusal, which is why it raises a plain
    `ValueError` the handler cannot trip. `dispatch_execution` takes the
    same parameter for the same reason.
    """
    if state is not None:
        raise ProcedureAlreadyExistsError(state.id)
    name = ProcedureName(command.name)
    beamline = ProcedureBeamline(command.beamline)
    steps = validated_steps(command.steps)
    if len(step_ids) != len(steps):
        msg = f"a definition needs one id per step: {len(step_ids)} given for {len(steps)} steps"
        raise ValueError(msg)
    for step in steps:
        if isinstance(step, RunStep) and context.operations[step.operation_id].is_retired:
            operation = context.operations[step.operation_id]
            raise OperationCannotBeCitedError(operation.id, operation.status)
    for index, step in enumerate(steps):
        if not isinstance(step, RunStep):
            continue
        try:
            validate_values_against_schema(
                step.parameters,
                context.operations[step.operation_id].parameters_schema,
                error_class=_ParametersRejectedError,
            )
        except _ParametersRejectedError as rejected:
            reason = f"they do not satisfy the operation it cites: {rejected}"
            raise InvalidProcedureParametersError(index, reason) from rejected
    for index, step in enumerate(steps):
        if not isinstance(step, RunStep):
            continue
        if not can_take_a_setup(context.operations[step.operation_id].parameters_schema):
            continue
        refusal = setup_refusal(
            step.parameters,
            context.setups,
            operation_id=step.operation_id,
            beamline=beamline.value,
        )
        if refusal is not None:
            raise InvalidProcedureParametersError(index, refusal)
    return [
        ProcedureDefined(
            procedure_id=new_id,
            procedure_name=name.value,
            beamline=beamline.value,
            steps=tuple(
                ComposedStep(id=step_id, step=step)
                for step_id, step in zip(step_ids, steps, strict=True)
            ),
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
