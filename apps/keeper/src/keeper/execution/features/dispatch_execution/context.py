"""The sibling state this slice's decision needs, loaded before deciding.

A decider is pure and never reads from a store. Dispatching copies a
procedure's name and steps onto the execution's genesis, and the procedure is
a different stream, so the handler does the reading and hands it across
as plain data.

The sibling of `define_procedure`'s, which loads an operation per run.
This one loads both: the procedure being handed out, and the operations
its runs cite, because the genesis carries their names as its routing
key.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from keeper.execution.aggregates.operation import Operation
from keeper.execution.aggregates.procedure import Procedure


@dataclass(frozen=True)
class DispatchExecutionContext:
    """The procedure being dispatched, as it stands right now.

    Read at handler time. A procedure has one event and nothing edits it,
    so unlike the operation a run reads this one cannot have changed between
    the read and the append. What it can be is absent, and the handler
    refuses that before building this.

    `operations` holds each distinct operation the runs cite, once,
    exactly as the sibling slice keys its own. Only the name is read, and
    the whole operation travels anyway because the handler has read the
    stream to get it and a context shaped to one field would have to
    change the day a second one is wanted.

    Every cited operation is present: the handler refuses a dispatch
    whose operation does not resolve before building this, so the decider
    may look one up without handling a miss.
    """

    procedure: Procedure
    operations: Mapping[UUID, Operation]


__all__ = ["DispatchExecutionContext"]
