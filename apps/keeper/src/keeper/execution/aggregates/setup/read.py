"""Load a Setup by replaying its stream, at its latest revision or at all of them.

Three loaders. The plain one answers what a setup holds now. The one with
the version is for the revising handler, which appends to a stream that
already has rows and passes the version it folded from back as
`expected_version`, so that two callers revising one setup at once
produce one revision and one conflict rather than two revisions that each
believe they followed the same one. The third keeps every revision, for a
reader asking what a setup said at an earlier one.

There is no setups table: the answer is recomputed from history on every
call. That is the right trade for one setup by id, where a stream is one
row per revision. It is the wrong trade for listing setups or finding one
by its name, which cannot replay everything; that is `summary.py`.

Lives with the aggregate rather than with a slice because it reads the
aggregate's whole stream, whatever command happened to write each row.
"""

from uuid import UUID

from keeper.execution.aggregates.setup.events import from_stored
from keeper.execution.aggregates.setup.evolver import fold, fold_revisions
from keeper.execution.aggregates.setup.state import Setup
from keeper.infrastructure.ports.event_store import EventStore

SETUP_STREAM_TYPE = "Setup"
"""The stream type every Setup event is stored under.

Half of the `(stream_type, event_type)` routing key. Declared as a
constant because the writing side and this reading side must agree on it
and they are in different files.
"""


async def load_setup(event_store: EventStore, setup_id: UUID) -> Setup | None:
    """Return the setup at its latest revision, or None if the stream is empty.

    An empty stream means no such setup was ever defined. The caller
    decides what that means on its own surface: a 404 over HTTP, an error
    result over MCP.
    """
    stored, _version = await event_store.load(SETUP_STREAM_TYPE, setup_id)
    return fold([from_stored(row) for row in stored])


async def load_setup_with_version(
    event_store: EventStore, setup_id: UUID
) -> tuple[Setup | None, int]:
    """Return the setup's state and the version it was folded from.

    The version is what the revising handler passes back as
    `expected_version`. Without it a second revision arriving at the same
    moment would land on top of the first, numbered as though the first
    had never happened, because it was decided against state that was
    already stale.
    """
    stored, version = await event_store.load(SETUP_STREAM_TYPE, setup_id)
    return fold([from_stored(row) for row in stored]), version


async def load_setup_revisions(event_store: EventStore, setup_id: UUID) -> tuple[Setup, ...]:
    """Return every revision of the setup, oldest first, or nothing if there is none.

    The nth element is revision n. One load whatever the revision asked
    for, because the stream has to be read from its start to reach any
    revision at all, and the last element is the latest.
    """
    stored, _version = await event_store.load(SETUP_STREAM_TYPE, setup_id)
    return fold_revisions([from_stored(row) for row in stored])


__all__ = [
    "SETUP_STREAM_TYPE",
    "load_setup",
    "load_setup_revisions",
    "load_setup_with_version",
]
