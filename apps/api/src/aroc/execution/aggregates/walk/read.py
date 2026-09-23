"""Load a Walk by replaying its stream.

One function, plus the version a writing handler needs. It loads the
stream, rebuilds each event, and folds them into current state. There is
no walks table: the answer is recomputed from history on every call.

A walk's stream is longer than a run's by construction, one row per step
plus two, so this is the loader that will feel a hundred-step procedure
first. It is still the right trade for reading one walk by id, and the
questions it is the wrong trade for are the ones the summary port
answers.

Two loaders, and the difference between them is the version. A handler
about to append needs the version it folded from, so that two reports of
one step produce one append and one conflict rather than two outcomes on
one step. A reader needs no such thing and gets the shorter function.
"""

from uuid import UUID

from aroc.execution.aggregates.walk.events import from_stored
from aroc.execution.aggregates.walk.evolver import fold
from aroc.execution.aggregates.walk.state import Walk
from aroc.infrastructure.ports.event_store import EventStore

WALK_STREAM_TYPE = "Walk"
"""The stream type every Walk event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_walk_with_version(event_store: EventStore, walk_id: UUID) -> tuple[Walk | None, int]:
    """Return the walk's current state and the version it was folded from.

    The version is what a writing handler passes back as
    `expected_version`, so that two drivers reporting the same walk at
    once produce one append and one `ConcurrencyError` rather than two
    records of one step.

    Reading it here rather than in the handler keeps the rebuild in one
    place: the state and the version it corresponds to come out of the
    same load, and nothing has to re-derive one from the other.
    """
    stored, version = await event_store.load(WALK_STREAM_TYPE, walk_id)
    return fold([from_stored(row) for row in stored]), version


async def load_walk(event_store: EventStore, walk_id: UUID) -> Walk | None:
    """Return the walk's current state, or None if the stream is empty.

    An empty stream means no such walk was ever recorded. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.

    For readers. A handler about to append wants `load_walk_with_version`
    instead, because appending without the version it read is how a lost
    update happens.
    """
    state, _version = await load_walk_with_version(event_store, walk_id)
    return state


__all__ = ["WALK_STREAM_TYPE", "load_walk", "load_walk_with_version"]
