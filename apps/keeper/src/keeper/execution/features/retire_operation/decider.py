"""The decision: what retiring an operation produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.execution.aggregates.operation import (
    Operation,
    OperationCannotBeRetiredError,
    OperationNotFoundError,
    OperationRetired,
)
from keeper.execution.features.retire_operation.command import RetireOperation


def decide(
    state: Operation | None,
    command: RetireOperation,
    *,
    now: datetime,
) -> list[OperationRetired]:
    """Decide the events produced by retiring an operation.

    Invariants:
      - State must not be None, or no such operation was defined
        -> OperationNotFoundError
      - The operation must not already be retired
        -> OperationCannotBeRetiredError

    Nothing about what cites it is asked, and that is deliberate. An
    operation cited by procedures that are still active may be retired:
    each of those dispatches is refused from then on, which is the point,
    because a dispatch of a routine nothing answers to waits forever.
    Refusing the retirement until every citing procedure had been retired
    first would need a read across every procedure stream, and would keep
    offering the routine for exactly as long as somebody forgot one.

    Retiring is not deleting. The stream stays, the schema stays readable,
    and every procedure and execution that cites the operation still
    resolves it.
    """
    if state is None:
        raise OperationNotFoundError(command.operation_id)
    if state.is_retired:
        raise OperationCannotBeRetiredError(state.id, state.status)
    return [OperationRetired(operation_id=command.operation_id, occurred_at=now)]


__all__ = ["decide"]
