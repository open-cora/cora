"""The decision: what dispatching a walk produces.

Pure. No awaits, no ports, no clock. `now` and `new_id` arrive as
parameters precisely so this function has nothing to invent.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from aroc.execution.aggregates.procedure import describes
from aroc.execution.aggregates.walk import (
    DispatchedStep,
    Walk,
    WalkAlreadyExistsError,
    WalkDispatched,
    WalkProcedureName,
    validated_steps,
)
from aroc.execution.features.dispatch_walk.command import DispatchWalk
from aroc.execution.features.dispatch_walk.context import DispatchWalkContext


def decide(
    state: Walk | None,
    command: DispatchWalk,
    *,
    context: DispatchWalkContext,
    now: datetime,
    new_id: UUID,
    step_ids: Sequence[UUID],
) -> list[WalkDispatched]:
    """Decide the events produced by dispatching a walk.

    Invariants:
      - State must be None, or the id already has a history
        -> WalkAlreadyExistsError
      - The procedure's name must be within the walk's bound
        -> InvalidWalkProcedureNameError
      - The rendered step list must be non-empty and bounded
        -> InvalidWalkStepsError

    The two value checks look redundant, because a procedure enforced its
    own bounds at definition and they are the same numbers. They are not
    redundant: the bounds are declared twice, on two aggregates, and
    nothing stops one moving. Running them here is what keeps a walk's
    record within the walk's own limits whatever the procedure's turn out
    to be, and the evolver runs them again on the way back out.

    That the procedure exists is NOT checked here. Discovering an absence
    needs the store, and the handler has already refused a dispatch
    naming one that does not.

    `step_ids` arrives minted rather than being made here, for the reason
    `new_id` does: this function is pure, and the ids have to be on the
    genesis payload so the fold produces the same steps on every replay.
    One per step, in order, and a list of the wrong length is a caller
    bug rather than a domain refusal, so the zip below is checked with an
    assertion the handler cannot trip.
    """
    if state is not None:
        raise WalkAlreadyExistsError(state.id)
    rendered = tuple(describes(step) for step in context.procedure.steps)
    if len(step_ids) != len(rendered):
        msg = f"dispatch needs one id per step: {len(step_ids)} given for {len(rendered)} steps"
        raise ValueError(msg)
    return [
        WalkDispatched(
            walk_id=new_id,
            procedure_id=command.procedure_id,
            procedure_name=WalkProcedureName(value=context.procedure.name.value).value,
            steps=list(
                validated_steps(
                    tuple(
                        DispatchedStep(id=step_id, describes=text)
                        for step_id, text in zip(step_ids, rendered, strict=True)
                    )
                )
            ),
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
