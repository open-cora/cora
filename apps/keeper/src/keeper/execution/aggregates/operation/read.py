"""Load an Operation by replaying its stream.

Two loaders, and the difference between them is the version. A handler
about to append to a stream that already has rows needs the version it
folded from, so that two callers retiring one operation at once, or
declaring its device use, produce one append and one conflict rather than
two rows the decider had no chance to refuse. A reader needs no such
thing and gets the shorter function.

There is no operations table: the answer is recomputed from history on
every call. That is the right trade for reading one operation by id, where
a stream is one row, or three once its device use is declared and it has
been retired. It is the wrong
trade for listing or filtering operations, which cannot replay everything
and needs a maintained summary table instead. That belongs in its own
module and is `summary.py`.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.execution.aggregates.operation.events import from_stored
from keeper.execution.aggregates.operation.evolver import fold
from keeper.execution.aggregates.operation.state import Operation
from keeper.infrastructure.ports.event_store import EventStore

OPERATION_STREAM_TYPE = "Operation"
"""The stream type every Operation event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_operation(event_store: EventStore, operation_id: UUID) -> Operation | None:
    """Return the operation's current state, or None if the stream is empty.

    An empty stream means no such operation was ever defined. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.
    """
    stored, _version = await event_store.load(OPERATION_STREAM_TYPE, operation_id)
    return fold([from_stored(row) for row in stored])


async def load_operation_with_version(
    event_store: EventStore, operation_id: UUID
) -> tuple[Operation | None, int]:
    """Return the operation's state and the version it was folded from.

    The version is what the retiring and declaring handlers pass back as
    `expected_version`, so that two callers writing to one operation at once
    produce one append and one `ConcurrencyError`. Without it the second
    append would land a retirement or a second declaration the decider had
    no chance to refuse, because it decided against state that was already
    stale.
    """
    stored, version = await event_store.load(OPERATION_STREAM_TYPE, operation_id)
    return fold([from_stored(row) for row in stored]), version


__all__ = ["OPERATION_STREAM_TYPE", "load_operation", "load_operation_with_version"]
