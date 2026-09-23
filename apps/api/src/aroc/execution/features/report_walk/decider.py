"""The decision: what reporting a walk produces.

Create-style, so `new_id` arrives and the state must be empty.

Pure. No awaits, no ports, no clock. Nothing is loaded from a sibling
stream either, and the absence is worth naming: a walk cites no plan and
no procedure, so unlike `report_run` there is nothing to check it
against. What it declares is its own steps, which is why they are
validated here rather than looked up.
"""

from datetime import datetime
from uuid import UUID

from aroc.execution.aggregates.walk import (
    Walk,
    WalkAlreadyExistsError,
    WalkProcedureName,
    WalkReported,
    validated_steps,
)
from aroc.execution.features.report_walk.command import ReportWalk


def decide(
    state: Walk | None,
    command: ReportWalk,
    *,
    now: datetime,
    new_id: UUID,
) -> list[WalkReported]:
    """Decide the events produced by reporting a walk.

    Invariants:
      - State must be None, or the id already has a history
        -> WalkAlreadyExistsError
      - The procedure name must be within its bound
        -> InvalidWalkProcedureNameError
      - The step list must be non-empty, bounded, and hold no blank step
        -> InvalidWalkStepsError

    Both value checks run here and again in the evolver, which is the
    both-directions posture every other value object in this context
    takes: a bound that only ran on the way in would let a stored row
    fold into a walk nothing could have written.

    What is NOT checked is whether another walk already names this same
    reference. Nothing here can see another stream, and the gap is the
    same one a run's external reference leaves open, for the same
    reason.
    """
    if state is not None:
        raise WalkAlreadyExistsError(state.id)
    return [
        WalkReported(
            walk_id=new_id,
            reference_scheme=command.reference.scheme,
            reference_value=command.reference.value,
            procedure_name=WalkProcedureName(value=command.procedure_name).value,
            steps=list(validated_steps(command.steps)),
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
