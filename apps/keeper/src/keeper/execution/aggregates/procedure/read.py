"""Load a Procedure by replaying its stream.

Two loaders, and the difference between them is the version. A handler
about to append to a stream that already has rows needs the version it
folded from, so that two callers retiring one procedure at once produce
one append and one conflict rather than two rows saying the same thing.
A reader needs no such thing and gets the shorter function.

There is no procedures table: the answer is recomputed from history on
every call. That is the right trade for reading one procedure by id,
where a stream is one row, or two once it has been retired. It is the
wrong trade for listing or filtering procedures, which cannot replay
everything and needs a maintained summary table instead. That belongs in
its own module and is `summary.py`.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.execution.aggregates.procedure.events import from_stored
from keeper.execution.aggregates.procedure.evolver import fold
from keeper.execution.aggregates.procedure.state import Procedure
from keeper.infrastructure.ports.event_store import EventStore

PROCEDURE_STREAM_TYPE = "Procedure"
"""The stream type every Procedure event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_procedure(event_store: EventStore, procedure_id: UUID) -> Procedure | None:
    """Return the procedure's current state, or None if the stream is empty.

    An empty stream means no such procedure was ever defined. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.
    """
    stored, _version = await event_store.load(PROCEDURE_STREAM_TYPE, procedure_id)
    return fold([from_stored(row) for row in stored])


async def load_procedure_with_version(
    event_store: EventStore, procedure_id: UUID
) -> tuple[Procedure | None, int]:
    """Return the procedure's state and the version it was folded from.

    The version is what the retiring handler passes back as
    `expected_version`, so that two callers retiring one procedure at once
    produce one append and one `ConcurrencyError`. Without it the second
    append would land a retirement the decider had no chance to refuse,
    because it decided against state that was already stale.
    """
    stored, version = await event_store.load(PROCEDURE_STREAM_TYPE, procedure_id)
    return fold([from_stored(row) for row in stored]), version


__all__ = ["PROCEDURE_STREAM_TYPE", "load_procedure", "load_procedure_with_version"]
