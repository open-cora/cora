"""Keep `proj_execution_setup_summary` in step with the setup streams.

Two event types over two statements. The genesis inserts a row at
revision 1, and each revision moves the row to the revision it carries and
the moment it was made. Nothing else happens to a setup, so nothing else is
written.

## Running twice must be harmless

Delivery is at-least-once. The worker advances its bookmark in the same
transaction as the writes, so a crash between the two replays the batch.

The genesis takes `ON CONFLICT (setup_id) DO NOTHING`. The revision is
harmless for a different reason: it writes the number the event carries
rather than adding one to the number the row holds, and it moves the row
only forward. A replayed revision finds the row at that number or past it
and leaves it where it is, which an increment could not do.

That is why the revision number rides `SetupRevised` at all. The fold
could count revisions without it; this statement could not, because a
count kept by adding is a count a replay doubles.

## The name is three things at once

`proj_execution_setup_summary` is the table, the bookmark row, and this
projection's registered name.
`test_projections_have_a_table_and_a_bookmark.py` is what makes the
agreement a rule rather than a habit.

## Why the key index is not unique

The defining handler refuses a second setup under a key already held, and
the refusal is a check rather than a lock, so a race can still land two. A
unique index here would swallow the second: the worker would catch the
violation, the row would never appear, and a setup that exists in the log
would be missing from every listing. Showing both is the better failure,
because a person can see it.
"""

from typing import Any
from uuid import UUID

from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_execution_setup_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "SetupDefined"
_REVISED_EVENT_TYPE = "SetupRevised"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    setup_id, beamline, operation_id, name, revision, created_at, revised_at
) VALUES ($1, $2, $3, $4, 1, $5, $5)
ON CONFLICT (setup_id) DO NOTHING
"""

_REVISE_SQL = f"""
UPDATE {PROJECTION_NAME}
SET revised_at = CASE WHEN revision < $2::integer THEN $3::timestamptz ELSE revised_at END,
    revision = GREATEST(revision, $2::integer)
WHERE setup_id = $1
"""
"""Move a row to the revision an event carries, and never back.

Both assignments read the row as it was before the statement, which is how
an UPDATE evaluates, so the time moves exactly when the number does. The
row is matched by id alone, so the count the statement reports is zero only
when the row is missing, which is the one case worth a warning.
"""

_log = get_logger(__name__)


class SetupSummaryProjection:
    """Folds setup events into one row per setup."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset({_GENESIS_EVENT_TYPE, _REVISED_EVENT_TYPE})

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one event into the table, inside the worker's transaction.

        Raising rolls the whole batch back and leaves the bookmark where it
        was, so an event this cannot handle is retried forever rather than
        skipped. That is the right failure for a read model: stale and loud
        beats wrong and quiet.
        """
        payload: dict[str, Any] = event.payload
        if event.event_type == _GENESIS_EVENT_TYPE:
            await conn.execute(
                _INSERT_SQL,
                event.stream_id,
                payload["beamline"],
                UUID(payload["operation_id"]),
                payload["setup_name"],
                event.occurred_at,
            )
            return
        await self._revise(event, int(payload["revision"]), conn)

    async def _revise(self, event: StoredEvent, revision: int, conn: ConnectionLike) -> None:
        """Move an existing row forward, or say so when there is none.

        A missing row means the genesis is missing, which the ordering
        guarantees cannot happen: events arrive in `(transaction_id,
        position)` order and a setup's own events share a stream. It is
        logged rather than raised, for the reason the operation projection
        gives: wedging every listing over one setup is worse than a warning
        naming it.
        """
        result = await conn.execute(_REVISE_SQL, event.stream_id, revision, event.occurred_at)
        if isinstance(result, str) and result.endswith(" 0"):
            _log.warning(
                "setup_summary.revision_without_row",
                projection=PROJECTION_NAME,
                setup_id=str(event.stream_id),
                revision=revision,
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "SetupSummaryProjection"]
