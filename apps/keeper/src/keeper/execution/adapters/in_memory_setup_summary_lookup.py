"""Answer the same questions by folding, when there is no table to read.

The in-memory half of the `SetupSummaryLookup` port, and the operation
lookup's sibling. Same reason for existing: this application boots and
answers with no database, which is what the unit and contract tiers run
against, and in that environment no projection worker runs so the table
the other adapter reads never fills.

Same trade too. Every setup stream, folded, sorted, filtered, paged, which
is the cost a projection exists to avoid and is free when the store is a
dictionary. `tests/_port_contracts/setup_summary_lookup.py` is what makes
"the two answer alike" a checkable claim rather than a hopeful one.

One difference from the table worth knowing: this side sees a setup the
moment its event is appended, where the table sees it once the worker has
caught up. So of the two windows the defining handler's docstring
describes, only one is open here: two definitions interleaving in one
process can still both find a key free, and a definition made a moment
ago is never missed.
"""

from uuid import UUID

from keeper.execution.aggregates.setup.events import from_stored
from keeper.execution.aggregates.setup.evolver import evolve
from keeper.execution.aggregates.setup.read import SETUP_STREAM_TYPE
from keeper.execution.aggregates.setup.state import Setup, SetupBeamline, SetupName
from keeper.execution.aggregates.setup.summary import SetupSummary, SetupSummaryPage
from keeper.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from keeper.infrastructure.projection.cursor import decode_cursor, encode_cursor


class InMemorySetupSummaryLookup:
    """Fold-everything implementation of the `SetupSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_setups(
        self,
        *,
        beamline: SetupBeamline | None,
        operation_id: UUID | None,
        name: SetupName | None,
        limit: int,
        cursor: str | None,
    ) -> SetupSummaryPage:
        """Return one page of setups, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if (beamline is None or summary.beamline == beamline)
            and (operation_id is None or summary.operation_id == operation_id)
            and (name is None or summary.name == name)
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.setup_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary for summary in summaries if (summary.created_at, summary.setup_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].setup_id)
            if has_more and page
            else None
        )
        return SetupSummaryPage(items=page, next_cursor=next_cursor)

    async def find_setup(
        self,
        *,
        beamline: SetupBeamline,
        operation_id: UUID,
        name: SetupName,
    ) -> SetupSummary | None:
        """Return the setup holding this key, the first defined if two do."""
        holding = sorted(
            (
                summary
                for summary in await self._all_summaries()
                if summary.beamline == beamline
                and summary.operation_id == operation_id
                and summary.name == name
            ),
            key=lambda summary: (summary.created_at, summary.setup_id),
        )
        return holding[0] if holding else None

    async def _all_summaries(self) -> list[SetupSummary]:
        """Fold every setup stream into the row a projection would write.

        `created_at` comes off the first envelope, the genesis, and
        `revised_at` off the envelope of the event that made the latest
        revision, which is the moment the table's revision statement
        records. Walked event by event rather than read off the last row,
        so the time follows the revision number and not merely the end of
        the stream.
        """
        summaries: list[SetupSummary] = []
        for setup_id in self._event_store.stream_ids(SETUP_STREAM_TYPE):
            stored, _version = await self._event_store.load(SETUP_STREAM_TYPE, setup_id)
            if not stored:
                continue
            state: Setup | None = None
            revised_at = stored[0].occurred_at
            for row in stored:
                before = state.revision if state is not None else 0
                state = evolve(state, from_stored(row))
                if state.revision != before:
                    revised_at = row.occurred_at
            if state is None:
                continue
            summaries.append(
                SetupSummary(
                    setup_id=state.id,
                    beamline=state.beamline,
                    operation_id=state.operation_id,
                    name=state.name,
                    revision=state.revision,
                    created_at=stored[0].occurred_at,
                    revised_at=revised_at,
                )
            )
        return summaries


__all__ = ["InMemorySetupSummaryLookup"]
