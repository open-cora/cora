"""The decision: what retiring a procedure produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.execution.aggregates.procedure import (
    Procedure,
    ProcedureCannotBeRetiredError,
    ProcedureNotFoundError,
    ProcedureRetired,
)
from keeper.execution.features.retire_procedure.command import RetireProcedure


def decide(
    state: Procedure | None,
    command: RetireProcedure,
    *,
    now: datetime,
) -> list[ProcedureRetired]:
    """Decide the events produced by retiring a procedure.

    Invariants:
      - State must not be None, or no such procedure was composed
        -> ProcedureNotFoundError
      - The procedure must not already be retired
        -> ProcedureCannotBeRetiredError

    The first is unreachable through the handler, which has to read the
    procedure before it can authorize against its beamline and refuses an
    absent one there. It is stated anyway, so the decision says what it
    relies on rather than assuming it.

    Nothing about the procedure's executions is asked. One already
    dispatched and not yet claimed stays dispatched: retiring says what
    may be handed out next, and an execution that exists was handed out
    already. Ending it is a different act with a different author.
    """
    if state is None:
        raise ProcedureNotFoundError(command.procedure_id)
    if state.is_retired:
        raise ProcedureCannotBeRetiredError(state.id, state.status)
    return [ProcedureRetired(procedure_id=command.procedure_id, occurred_at=now)]


__all__ = ["decide"]
