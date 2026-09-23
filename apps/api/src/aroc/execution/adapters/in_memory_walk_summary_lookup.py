"""Answer the same question by folding, when there is no table to read.

The in-memory half of the `WalkSummaryLookup` port. It exists because
this application is meant to boot and answer with no database at all,
which is what the unit and contract tiers run against. In that
environment no projection worker runs, so the table the other adapter
reads does not exist and never fills.

So this one recomputes. Every walk stream, folded, sorted, filtered,
paged. That is precisely the cost a projection exists to avoid, and it
is the right trade here: the store is a dictionary, the streams number
in the tens, and the alternative is a surface that works in production
and refuses in every test.

## Why the two halves can be trusted to agree

They cannot, on inspection.
`tests/_port_contracts/walk_summary_lookup.py` is one suite run against
both, which is the only thing that makes the claim checkable.

The fold reaches the progress count a different way than the table
does, which is worth knowing when one of them is wrong. Here it counts
the steps the evolver marked reported; there it reads the size of a set
the projection unioned into. Two routes to one number is what the
contract suite is comparing.
"""

from aroc.execution.aggregates.walk.events import from_stored
from aroc.execution.aggregates.walk.evolver import fold
from aroc.execution.aggregates.walk.read import WALK_STREAM_TYPE
from aroc.execution.aggregates.walk.summary import WalkSummary, WalkSummaryPage
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.projection.cursor import decode_cursor, encode_cursor
from aroc.shared.identifier import Identifier


class InMemoryWalkSummaryLookup:
    """Fold-everything implementation of the `WalkSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_walks(
        self,
        *,
        reference: Identifier | None,
        limit: int,
        cursor: str | None,
    ) -> WalkSummaryPage:
        """Return one page of walks, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if reference is None or summary.reference == reference
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.walk_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary for summary in summaries if (summary.created_at, summary.walk_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].walk_id)
            if has_more and page
            else None
        )
        return WalkSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[WalkSummary]:
        """Fold every walk stream into the row a projection would have written.

        `created_at` is the first event's domain time and `updated_at`
        the largest of them, which is not the same as the last one's. A
        driver may report a step late, and the table takes the greater
        of the two for that reason, so taking the last here would put
        the two halves of this port one row apart.
        """
        summaries: list[WalkSummary] = []
        for walk_id in self._event_store.stream_ids(WALK_STREAM_TYPE):
            stored, _version = await self._event_store.load(WALK_STREAM_TYPE, walk_id)
            walk = fold([from_stored(row) for row in stored])
            if walk is None:
                continue
            summaries.append(
                WalkSummary(
                    walk_id=walk.id,
                    reference=walk.reference,
                    procedure_name=walk.procedure_name.value,
                    step_count=walk.step_count,
                    reported_count=walk.reported_count,
                    ended=walk.ended,
                    created_at=stored[0].occurred_at,
                    updated_at=max(row.occurred_at for row in stored),
                )
            )
        return summaries


__all__ = ["InMemoryWalkSummaryLookup"]
