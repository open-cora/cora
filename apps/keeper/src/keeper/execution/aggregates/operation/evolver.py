"""Replay Operation events to reconstruct current state.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.

Both are pure and total: the same events in the same order always give
the same state, on any machine, years apart. That is the property the
whole approach rests on, and it is why nothing here reads a clock, a
config value or a database.

The status is computed here and stored nowhere. The genesis sets it
active and the retirement sets it retired, so the value can never
disagree with the history behind it. A retirement changes nothing else:
the name and the schema carry through, because a retired operation is
still a record of what was written down.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from keeper.execution.aggregates.operation.events import (
    OperationDefined,
    OperationEvent,
    OperationRetired,
)
from keeper.execution.aggregates.operation.state import (
    Operation,
    OperationName,
    OperationStatus,
)
from keeper.infrastructure.slices.evolver import require_state


def evolve(state: Operation | None, event: OperationEvent) -> Operation:
    """Apply one event to the state before it.

    The genesis arm builds the operation and ignores the prior state, which
    must be None. The retirement arm requires one, because nothing can be
    retired that was never defined.

    Two things happen on the way through the genesis that are easy to
    read past. The name goes back through `OperationName`, so a row whose
    name no longer passes the bound fails here rather than folding into an
    operation nothing could have written. And the schema is shallow-copied,
    so the dict on the state and the dict in the payload that built it are
    not the same object: mutating either would otherwise change the other.
    """
    match event:
        case OperationDefined(
            operation_id=operation_id,
            operation_name=operation_name,
            parameters_schema=parameters_schema,
        ):
            _ = state
            return Operation(
                id=operation_id,
                name=OperationName(operation_name),
                parameters_schema=dict(parameters_schema),
                status=OperationStatus.ACTIVE,
            )
        case OperationRetired():
            return replace(require_state(state, "OperationRetired"), status=OperationStatus.RETIRED)
        case _:
            assert_never(event)


def fold(events: Sequence[OperationEvent]) -> Operation | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Operation | None = None
    for event in events:
        state = evolve(state, event)
    return state


__all__ = ["evolve", "fold"]
