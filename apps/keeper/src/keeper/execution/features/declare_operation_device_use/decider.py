"""The decision: what declaring an operation's device use produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from keeper.execution.aggregates.operation import (
    Operation,
    OperationDeviceUseCannotBeDeclaredError,
    OperationDeviceUseDeclared,
    OperationNotFoundError,
)
from keeper.execution.features.declare_operation_device_use.command import (
    DeclareOperationDeviceUse,
)


def decide(
    state: Operation | None,
    command: DeclareOperationDeviceUse,
    *,
    now: datetime,
) -> list[OperationDeviceUseDeclared]:
    """Decide the events produced by declaring an operation's device use.

    Invariants:
      - State must not be None, or no such operation was defined
        -> OperationNotFoundError
      - The operation must not be retired
        -> OperationDeviceUseCannotBeDeclaredError
      - Its device use must not be declared already, whichever way
        -> OperationDeviceUseCannotBeDeclaredError

    Retirement is asked first. Nothing composes a run of a retired
    operation, so a declaration would govern nothing, and telling a
    caller it was declared already would send it looking at a value that
    no longer decides anything.

    A second declaration is refused even when it agrees with the first,
    for the reason a schema is never edited: what a run was composed
    under has to stay what the operation says. A caller retrying its own
    declaration hears a 409 carrying the value it already wrote, which is
    how it can tell its first attempt landed.
    """
    if state is None:
        raise OperationNotFoundError(command.operation_id)
    if state.is_retired or state.drives_devices is not None:
        raise OperationDeviceUseCannotBeDeclaredError(
            state.id, status=state.status, drives_devices=state.drives_devices
        )
    return [
        OperationDeviceUseDeclared(
            operation_id=command.operation_id,
            drives_devices=command.drives_devices,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
