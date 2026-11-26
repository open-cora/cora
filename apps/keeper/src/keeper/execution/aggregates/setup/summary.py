"""One row per setup, and the port that reads those rows.

The Operation's sibling, and the same split: `read.py` answers a question
that names a setup by its id, and this answers the two that do not. What
setups a beamline holds for an operation, and which one a name means.

## Why the key lookup returns one answer when the operation's cannot

Two operations may share a name on purpose, so a name lookup over
operations returns a page and leaves the choice to the caller. A setup's
key is meant to be unique: the defining handler refuses a second setup
under a key already held, so `find_setup` answers with one setup or none.

Meant to be, and not guaranteed. That refusal is a check made before the
append rather than a lock, so two definitions racing each other can both
land. When that has happened the lookup returns the one defined first,
which is the one the check would have kept had it been a lock, and the
listing shows both, which is where a person finds the other.

## Why the row is so thin

The settings and their schema are not here. Either may be as large as the
operation's own schema, a page of fifty would be a page of documents, and
a caller that wants them has the id and one call to `get_setup`.

What a row carries instead is how far the setup has come: the revision it
is at and when that revision was made. `revised_at` is the moment the
revision on the row was written, so for a setup still at revision 1 it is
the moment it was defined. A null there would say the same thing less
plainly, and would make every reader ordering by it handle the case.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.setup.state import SetupBeamline, SetupName


@dataclass(frozen=True)
class SetupSummary:
    """A setup as a list shows it.

    `created_at` is when the setup was defined and `revised_at` when its
    latest revision was made, both taken from the envelope's domain time.
    For a setup the two times the envelope carries are the same instant to
    within a round trip, because a setup is authored here rather than
    reported from somewhere else.
    """

    setup_id: UUID
    beamline: SetupBeamline
    operation_id: UUID
    name: SetupName
    revision: int
    created_at: datetime
    revised_at: datetime


@dataclass(frozen=True)
class SetupSummaryPage:
    """One page of summaries, newest first, and how to ask for the next.

    Newest by definition rather than by revision, so a setup keeps its
    place in a listing however often it is revised, and a caller paging
    through does not meet it twice.

    `next_cursor` is None when this is the last page. Opaque on purpose:
    it encodes the sort key of the final row, and a caller that takes it
    apart is depending on an ordering this is free to change.
    """

    items: list[SetupSummary]
    next_cursor: str | None


class SetupSummaryLookup(Protocol):
    """Read setups by something other than their id."""

    async def list_setups(
        self,
        *,
        beamline: SetupBeamline | None,
        operation_id: UUID | None,
        name: SetupName | None,
        limit: int,
        cursor: str | None,
    ) -> SetupSummaryPage:
        """Return one page of setups, newest first.

        Each filter narrows by equality, and together they narrow to the
        intersection. All three given is the key, which holds one setup
        unless a race let a second through.

        None of the three has a default, for the reason the procedure port
        gives about its filters: an adapter that may omit one is one a
        caller can silently lose it to, and the loss reads as a correct
        answer to a question nobody asked.

        `cursor` continues a previous page and comes from its
        `next_cursor`. A cursor that does not decode raises
        `InvalidCursorError`.
        """
        ...

    async def find_setup(
        self,
        *,
        beamline: SetupBeamline,
        operation_id: UUID,
        name: SetupName,
    ) -> SetupSummary | None:
        """Return the setup holding this key, or None if no setup does.

        The question the defining handler asks before it writes, so that a
        second definition under one key is refused; it is the question a
        step naming a setup comes down to as well. If a race let two
        definitions under one key through, the one defined first is
        returned, by the same `(created_at, setup_id)` order the listing
        pages by.
        """
        ...


__all__ = ["SetupSummary", "SetupSummaryLookup", "SetupSummaryPage"]
