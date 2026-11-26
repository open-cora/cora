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
from keeper.execution.aggregates.setup import Setup, SetupName


@dataclass(frozen=True)
class DispatchExecutionContext:
    """The procedure being dispatched, as it stands right now.

    Read at handler time. Nothing edits a procedure's steps, so those
    cannot have changed between the read and the append. Its status can:
    a retirement landing in that window is not seen, and the dispatch
    goes through. That is accepted for the reason `define_procedure`
    accepts the same of an operation: closing it would mean a transaction
    over two streams, and what the refusal is for is a caller dispatching
    something retired long ago, not a race with the retiring. What the
    procedure can also be is absent, and the handler refuses that before
    building this.

    `operations` holds each distinct operation the runs cite, once,
    exactly as the sibling slice keys its own. Two things are read off
    each: the name, which the genesis carries as its routing key, and the
    status, which refuses an operation nothing answers to. The whole
    operation travels because the handler has read the stream to get it,
    and this is the day a second field was wanted.

    Every cited operation is present: the handler refuses a dispatch
    whose operation does not resolve before building this, so the decider
    may look one up without handling a miss.

    `setups` holds the setup each setup-taking run names, resolved again
    now by name at the procedure's beamline and folded to its latest
    revision, keyed by operation and name. Again rather than carried from
    the procedure's definition, because a procedure names a setup and does
    not cite one: the setup it named may have been revised since, and a
    procedure in the log from before setups were checked may name one that
    has only just been defined. A miss is expected and is the decider's to
    refuse. No default, so a caller that resolved none says so with an
    empty mapping and every run that takes a setup is refused.
    """

    procedure: Procedure
    operations: Mapping[UUID, Operation]
    setups: Mapping[tuple[UUID, SetupName], Setup]


__all__ = ["DispatchExecutionContext"]
