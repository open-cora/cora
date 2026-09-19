"""Answer the same questions by folding, when there is no table to read.

The in-memory half of the `RunSummaryLookup` port. It exists because this
application is meant to boot and answer with no database at all, which is
what the unit and contract tiers run against and what the Bluesky spike
drives. In that environment no projection worker runs, so the table the
other adapter reads does not exist and never fills.

So this one recomputes. Every run stream, folded, sorted, filtered, paged.
That is precisely the cost a projection exists to avoid, and it is the
right trade here: the store is a dictionary, the streams number in the
tens, and the alternative is a surface that works in production and
refuses in every test.

## Why the two halves can be trusted to agree

They cannot, on inspection. `tests/_port_contracts/run_summary_lookup.py`
is one suite run against both, which is the only thing that makes the
claim checkable, and `test_port_contracts_have_two_sides.py` fails if the
second driver ever goes away.

The one thing this cannot reproduce is lag. A projection is eventually
consistent and this is immediate, so a test that passes here says nothing
about a caller reading too soon. That is the integration tier's job, and
`drain_projections` is how it asks the question without sleeping.
"""

from aroc.execution.aggregates.run.events import from_stored
from aroc.execution.aggregates.run.evolver import fold
from aroc.execution.aggregates.run.read import RUN_STREAM_TYPE
from aroc.execution.aggregates.run.summary import RunSummary, RunSummaryPage
from aroc.infrastructure.adapters.in_memory_event_store import InMemoryEventStore
from aroc.infrastructure.projection.cursor import decode_cursor, encode_cursor
from aroc.shared.identifier import Identifier


class InMemoryRunSummaryLookup:
    """Fold-everything implementation of the `RunSummaryLookup` port.

    Typed against the concrete in-memory store rather than the
    `EventStore` port, because enumerating streams is not something the
    port offers and should not become something it offers. An adapter for
    the in-memory environment depending on the in-memory store is honest
    about what it is.
    """

    def __init__(self, event_store: InMemoryEventStore) -> None:
        self._event_store = event_store

    async def list_runs(
        self,
        *,
        external_ref: Identifier | None,
        limit: int,
        cursor: str | None,
    ) -> RunSummaryPage:
        """Return one page of runs, newest first."""
        summaries = [
            summary
            for summary in await self._all_summaries()
            if external_ref is None or summary.external_ref == external_ref
        ]
        summaries.sort(key=lambda summary: (summary.created_at, summary.run_id), reverse=True)

        after = decode_cursor(cursor) if cursor is not None else None
        if after is not None:
            summaries = [
                summary for summary in summaries if (summary.created_at, summary.run_id) < after
            ]

        page, has_more = summaries[:limit], len(summaries) > limit
        next_cursor = (
            encode_cursor(created_at=page[-1].created_at, item_id=page[-1].run_id)
            if has_more and page
            else None
        )
        return RunSummaryPage(items=page, next_cursor=next_cursor)

    async def _all_summaries(self) -> list[RunSummary]:
        """Fold every run stream into the row a projection would have written.

        The two timestamps come off the envelope, first event and last,
        the same two values the projection's INSERT and UPDATE write. The
        rest comes from the fold, so the status here is the evolver's own
        answer rather than a second mapping that could disagree with it.
        """
        summaries: list[RunSummary] = []
        for run_id in self._event_store.stream_ids(RUN_STREAM_TYPE):
            stored, _version = await self._event_store.load(RUN_STREAM_TYPE, run_id)
            run = fold([from_stored(row) for row in stored])
            if run is None:
                continue
            summaries.append(
                RunSummary(
                    run_id=run.id,
                    plan_id=run.plan_id,
                    external_ref=run.external_ref,
                    status=run.status,
                    created_at=stored[0].occurred_at,
                    updated_at=stored[-1].occurred_at,
                )
            )
        return summaries


__all__ = ["InMemoryRunSummaryLookup"]
