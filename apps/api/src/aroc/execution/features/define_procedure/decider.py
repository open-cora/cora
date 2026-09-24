"""The decision: what defining a procedure produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from datetime import datetime
from uuid import UUID

from aroc.execution.aggregates.procedure import (
    AcquireStep,
    InvalidProcedureParametersError,
    Procedure,
    ProcedureAlreadyExistsError,
    ProcedureDefined,
    ProcedureName,
    validated_steps,
)
from aroc.execution.features.define_procedure.command import DefineProcedure
from aroc.execution.features.define_procedure.context import DefineProcedureContext
from aroc.shared.json_schema.validation import validate_values_against_schema


class _ParametersRejectedError(ValueError):
    """What the shared validator raises here, before the step is named.

    The validator constructs its error class from a reason alone, and the
    refusal this slice publishes also carries which step the reason came
    from. So the reason is caught in this private shape and re-raised in
    the public one, one line below, rather than leaving a caller with a
    procedure told only that one of its acquisitions is wrong.
    """


def decide(
    state: Procedure | None,
    command: DefineProcedure,
    *,
    context: DefineProcedureContext,
    now: datetime,
    new_id: UUID,
) -> list[ProcedureDefined]:
    """Decide the events produced by defining a procedure.

    Invariants:
      - State must be None, or the id already has a history
        -> ProcedureAlreadyExistsError
      - The name must be non-empty and within the length bound
        -> InvalidProcedureNameError
      - The step list must be non-empty, within the length bound, and
        every step storable -> InvalidProcedureStepsError
      - Every acquisition's parameters must satisfy the schema its plan
        declares -> InvalidProcedureParametersError

    The order is deliberate and runs cheapest first. The stream check
    comes first because it is about whether this command may be answered
    at all. The name is next because it is one comparison. The step list
    is checked whole before any parameters are, so a caller who sent a
    malformed step hears about that rather than about a schema failure
    caused by it.

    That a cited plan exists is NOT checked here. It needs a store, and
    the handler has already refused a procedure citing one that does not.

    An acquisition supplying no parameters at all is accepted whatever
    its plan requires, because the shared validator defers `required` to
    the point the values are acted on. Reporting a run has the same gap
    and for the same reason: the check here is carrier-side, and the
    thing finally resolving the values is the engine.
    """
    if state is not None:
        raise ProcedureAlreadyExistsError(state.id)
    name = ProcedureName(command.name)
    steps = validated_steps(command.steps)
    for index, step in enumerate(steps):
        if not isinstance(step, AcquireStep):
            continue
        try:
            validate_values_against_schema(
                step.parameters,
                context.plans[step.plan_id].parameters_schema,
                error_class=_ParametersRejectedError,
            )
        except _ParametersRejectedError as rejected:
            raise InvalidProcedureParametersError(index, str(rejected)) from rejected
    return [
        ProcedureDefined(
            procedure_id=new_id,
            procedure_name=name.value,
            steps=steps,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
