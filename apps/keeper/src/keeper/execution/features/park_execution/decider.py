"""The decision: what parking an execution produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.execution.aggregates.execution import (
    Execution,
    ExecutionAlreadyEndedError,
    ExecutionCannotBeParkedError,
    ExecutionNotFoundError,
    ExecutionParked,
    ExecutionStatus,
    StepOutcome,
)
from keeper.execution.features.park_execution.command import ParkExecution


def decide(
    state: Execution | None,
    command: ParkExecution,
    *,
    now: datetime,
) -> list[ExecutionParked]:
    """Decide the events produced by parking an execution.

    Invariants:
      - State must not be None, or no such execution was dispatched
        -> ExecutionNotFoundError
      - The execution must not have ended
        -> ExecutionAlreadyEndedError
      - It must not be parked already, and the last step reported must
        have been handed off, so there is work for it to wait on
        -> ExecutionCannotBeParkedError

    An ended execution is refused with the error every other late arrival
    gets, rather than with this slice's own, because being closed is the
    more useful fact and a caller already handles it for a step report and
    an ending.

    The handed-off step's work may already have stopped, reported by
    whatever watches it between the driver's report of the step and this
    request. That is not refused: the driver could not have known, and the
    fold reads such an execution as ready the moment it is parked.

    Nothing checks that steps remain after the handed-off one. A walk that
    hands off its last step parks too, so the execution stays open until
    the work it handed off has stopped, and closing it then is a driver's
    to do. An ending sent at the handoff instead would read as finished
    while the last of its work was still running.
    """
    if state is None:
        raise ExecutionNotFoundError(command.execution_id)
    if state.ended:
        raise ExecutionAlreadyEndedError(command.execution_id)
    last = state.last_reported
    already = state.status in (ExecutionStatus.PARKED, ExecutionStatus.READY)
    if already or last is None or last.outcome is not StepOutcome.HANDED_OFF:
        raise ExecutionCannotBeParkedError(
            command.execution_id,
            state.status,
            last=None if last is None else last.outcome,
        )
    return [ExecutionParked(execution_id=command.execution_id, occurred_at=now)]


__all__ = ["decide"]
