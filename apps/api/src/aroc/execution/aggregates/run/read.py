"""Load a Run by replaying its stream.

One function. It loads the stream, rebuilds each event, and folds them
into current state. There is no runs table: the answer is recomputed from
history on every call.

That is the right trade for reading one run by id, where a stream is a
single row today and a handful once a run can end. It is the wrong trade
for listing runs or finding the one matching an external reference, and
the second of those is the query the first adapter will want. Neither can
replay everything; both need a maintained summary table, and a query of
that shape belongs in its own module.

Two loaders, and the difference between them is the version. A handler
about to append to a stream that already has rows needs the version it
folded from, so that two callers ending the same run at once produce one
append and one conflict rather than two endings on one run. A reader
needs no such thing and gets the shorter function.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from aroc.execution.aggregates.run.events import from_stored
from aroc.execution.aggregates.run.evolver import fold
from aroc.execution.aggregates.run.state import Run
from aroc.infrastructure.ports.event_store import EventStore

RUN_STREAM_TYPE = "Run"
"""The stream type every Run event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_run_with_version(event_store: EventStore, run_id: UUID) -> tuple[Run | None, int]:
    """Return the run's current state and the version it was folded from.

    The version is what a writing handler passes back as
    `expected_version`, so that two callers ending the same run at once
    produce one append and one `ConcurrencyError` rather than two
    endings.

    Reading it here rather than in the handler keeps the rebuild in one
    place: the state and the version it corresponds to come out of the
    same load, and nothing has to re-derive one from the other.
    """
    stored, version = await event_store.load(RUN_STREAM_TYPE, run_id)
    return fold([from_stored(row) for row in stored]), version


async def load_run(event_store: EventStore, run_id: UUID) -> Run | None:
    """Return the run's current state, or None if the stream is empty.

    An empty stream means no such run was ever recorded. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.

    For readers. A handler about to append wants
    `load_run_with_version` instead, because appending without the
    version it read is how a lost update happens.
    """
    state, _version = await load_run_with_version(event_store, run_id)
    return state


__all__ = ["RUN_STREAM_TYPE", "load_run", "load_run_with_version"]
