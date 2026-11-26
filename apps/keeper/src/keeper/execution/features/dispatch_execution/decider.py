"""The decision: what dispatching an execution produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from keeper.execution.aggregates.execution import (
    DispatchedStep,
    Execution,
    ExecutionAlreadyExistsError,
    ExecutionBeamline,
    ExecutionDispatched,
    ExecutionEvent,
    ExecutionProcedureName,
    ExecutionSetupsPinned,
    PinnedSetup,
    SetupPin,
    validated_steps,
)
from keeper.execution.aggregates.operation import OperationCannotBeCitedError
from keeper.execution.aggregates.procedure import (
    ProcedureCannotBeDispatchedError,
    RunStep,
    describes,
    runs_operation,
)
from keeper.execution.aggregates.setup import (
    SetupCannotBePinnedError,
    can_take_a_setup,
    named_setup,
    setup_refusal,
)
from keeper.execution.features.dispatch_execution.command import DispatchExecution
from keeper.execution.features.dispatch_execution.context import DispatchExecutionContext


def decide(
    state: Execution | None,
    command: DispatchExecution,
    *,
    context: DispatchExecutionContext,
    now: datetime,
    new_id: UUID,
    step_ids: Sequence[UUID],
) -> list[ExecutionEvent]:
    """Decide the events produced by dispatching an execution.

    Invariants:
      - State must be None, or the id already has a history
        -> ExecutionAlreadyExistsError
      - The procedure must not have been retired
        -> ProcedureCannotBeDispatchedError
      - No operation its runs cite may have been retired
        -> OperationCannotBeCitedError
      - Every run of an operation that takes a setup must name, in its
        config, a setup held for that operation at the procedure's
        beamline, and its override must fit that setup's latest revision
        -> SetupCannotBePinnedError
      - The procedure's name must be within the execution's bound
        -> InvalidExecutionProcedureNameError
      - The procedure's beamline must be within the execution's bound
        -> InvalidExecutionBeamlineError
      - The rendered step list must be non-empty and bounded
        -> InvalidExecutionStepsError

    The value checks look redundant, because a procedure enforced its own
    bounds at definition and they are the same numbers. They are not
    redundant: the bounds are declared twice, on two aggregates, and
    nothing stops one moving. Running them here is what keeps an execution's
    record within the execution's own limits whatever the procedure's turn out
    to be, and the evolver runs them again on the way back out.

    That the procedure exists is NOT checked here. Discovering an absence
    needs the store, and the handler has already refused a dispatch
    naming one that does not. The same holds of each operation a run
    cites, which is why the lookup below cannot miss.

    Whether either has been retired IS checked here, and both refusals
    exist for one reason: an execution nobody will claim waits forever,
    and while it waits it looks exactly like one that is merely slow. The
    procedure's own status is asked first because it is the fact the
    dispatch named. An active procedure running a retired operation is
    the case retiring the operation alone leaves behind, and refusing it
    here means the procedure need not be retired as well for the dispatch
    to stop. Both live here rather than in the handler so that
    `compose_one_run`, which calls this function directly, refuses them
    too.

    The setups are asked about after the operations, because a setup
    serves an operation and a refusal about a retired operation is the
    fact the caller has to act on first. A setup is resolved by name, now:
    the procedure names it rather than citing one, so the revision a step
    runs with is the one latest at dispatch, and the override is checked
    against that revision rather than the one the procedure was defined
    beside. That is also what lets a procedure from before setups were
    checked dispatch once a setup holds the name it carries.

    What a dispatch settles about setups it writes down: one more event,
    in the same list and so in the same append, pinning each such step to
    the setup and revision it will run with. A procedure none of whose
    runs takes a setup produces the genesis alone, exactly as before
    setups existed.

    The routines are sorted and de-duplicated, so a procedure running one
    operation at twenty sample positions names it once and a replay
    renders the same payload it rendered the first time.

    `step_ids` arrives minted rather than being made here, for the reason
    `new_id` does: this function is pure, and the ids have to be on the
    genesis payload so the fold produces the same steps on every replay.
    One per step, in order, and a list of the wrong length is a caller
    bug rather than a domain refusal, so the zip below is checked with an
    assertion the handler cannot trip.
    """
    if state is not None:
        raise ExecutionAlreadyExistsError(state.id)
    if context.procedure.is_retired:
        raise ProcedureCannotBeDispatchedError(context.procedure.id, context.procedure.status)
    composed = context.procedure.steps
    if len(step_ids) != len(composed):
        msg = f"dispatch needs one id per step: {len(step_ids)} given for {len(composed)} steps"
        raise ValueError(msg)
    cited = [runs_operation(step.step) for step in composed]
    for operation_id in cited:
        if operation_id is not None and context.operations[operation_id].is_retired:
            raise OperationCannotBeCitedError(operation_id, context.operations[operation_id].status)
    pins: list[SetupPin] = []
    beamline = context.procedure.beamline.value
    for index, (step_id, step) in enumerate(zip(step_ids, composed, strict=True)):
        run = step.step
        if not isinstance(run, RunStep):
            continue
        if not can_take_a_setup(context.operations[run.operation_id].parameters_schema):
            continue
        refusal = setup_refusal(
            run.parameters, context.setups, operation_id=run.operation_id, beamline=beamline
        )
        if refusal is not None:
            raise SetupCannotBePinnedError(index, refusal)
        name = named_setup(run.parameters)
        if name is None:
            msg = "a run the setup check passed names no setup, which that check refuses"
            raise RuntimeError(msg)
        setup = context.setups[(run.operation_id, name)]
        pins.append(
            SetupPin(
                step_id=step_id,
                setup=PinnedSetup(setup_id=setup.id, revision=setup.revision),
            )
        )
    routines = sorted(
        {
            context.operations[operation_id].name.value
            for operation_id in cited
            if operation_id is not None
        }
    )
    events: list[ExecutionEvent] = [
        ExecutionDispatched(
            execution_id=new_id,
            procedure_id=command.procedure_id,
            procedure_name=ExecutionProcedureName(value=context.procedure.name.value).value,
            beamline=ExecutionBeamline(value=context.procedure.beamline.value).value,
            steps=list(
                validated_steps(
                    tuple(
                        DispatchedStep(
                            id=step_id,
                            describes=describes(step.step),
                            procedure_step_id=step.id,
                        )
                        for step_id, step in zip(step_ids, composed, strict=True)
                    )
                )
            ),
            routines=routines,
            occurred_at=now,
        )
    ]
    if pins:
        events.append(ExecutionSetupsPinned(execution_id=new_id, pins=tuple(pins), occurred_at=now))
    return events


__all__ = ["decide"]
