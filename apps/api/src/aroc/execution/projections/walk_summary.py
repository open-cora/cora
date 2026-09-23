"""Keep `proj_execution_walk_summary` in step with the walk streams.

## Why this one cannot use a counter

Delivery is at-least-once. The worker advances its bookmark in the same
transaction as the writes, so a crash between the two replays the batch,
and a replayed batch has to leave the table where the first pass left
it.

Every other projection here satisfies that by writing absolute values: a
status derived from the event type is the same value however many times
it is written. Progress through a walk is not a value of that kind. A
column incremented per step would count a replayed step twice, and the
summary would report a walk further along than it is, which is the one
lie a record of an abandoned walk must not tell.

So the row holds the set of indices reported rather than a count of
them, and each step event unions one index into it. A union is
idempotent where an increment is not, and the count a caller reads is
the size of the set. The array is the mechanism; `reported_count` is
what the port exposes.

## The name is three things at once

`proj_execution_walk_summary` is the table, the bookmark row, and this
projection's registered name. They have to agree, because the worker
finds the bookmark by the name and the SQL below finds the table by
spelling it.

## What a duplicated reference does

Nothing. There is no unique index on the reference pair, so two records
of one walk make two rows and a caller filtering on the reference sees
both. A unique index would enforce uniqueness by dropping the second row
here, leaving a walk that exists in the log missing from every listing.
"""

from typing import Any

from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.infrastructure.projection.subscriber import ConnectionLike

_log = get_logger(__name__)

PROJECTION_NAME = "proj_execution_walk_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "WalkReported"
_ENDING_EVENT_TYPE = "WalkEnded"

STEP_EVENT_TYPES = frozenset(
    {"WalkStepDone", "WalkStepRefused", "WalkStepBroken", "WalkStepSkipped"}
)
"""The four events that report one step, whatever the outcome was.

Public because the check that keeps it in step with the aggregate's
event union lives in another module. A set only this file can read is a
set only this file can be wrong about.

The summary records that a step was reported and not how it ended. Which
outcome it was is on the event and in the walk's own record; a list view
asking "how far did this get" does not need it, and a column per outcome
would be four columns to keep idempotent instead of one array.
"""

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    walk_id, reference_scheme, reference_value, procedure_name,
    step_count, reported_indices, ended, created_at, updated_at
) VALUES ($1, $2, $3, $4, $5, '{{}}'::int[], false, $6, $6)
ON CONFLICT (walk_id) DO NOTHING
"""

_STEP_SQL = f"""
UPDATE {PROJECTION_NAME}
SET reported_indices = (
        SELECT array_agg(DISTINCT index ORDER BY index)
        FROM unnest(reported_indices || $2::int) AS index
    ),
    updated_at = GREATEST(updated_at, $3)
WHERE walk_id = $1
"""

_END_SQL = f"""
UPDATE {PROJECTION_NAME}
SET ended = true, updated_at = GREATEST(updated_at, $2)
WHERE walk_id = $1
"""


class WalkSummaryProjection:
    """Folds walk events into one row per walk."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset(
        {_GENESIS_EVENT_TYPE, _ENDING_EVENT_TYPE, *STEP_EVENT_TYPES},
    )

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one event into the table, inside the worker's transaction.

        Raising rolls the whole batch back and leaves the bookmark where
        it was, so an event this cannot handle is retried forever rather
        than skipped. That is the right failure for a read model: stale
        and loud beats wrong and quiet.
        """
        if event.event_type == _GENESIS_EVENT_TYPE:
            await self._insert(event, conn)
            return
        if event.event_type == _ENDING_EVENT_TYPE:
            await self._apply(event, conn, _END_SQL, event.stream_id, event.occurred_at)
            return
        await self._apply(
            event,
            conn,
            _STEP_SQL,
            event.stream_id,
            int(event.payload["index"]),
            event.occurred_at,
        )

    async def _insert(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write the genesis row, with no step reported yet.

        `walk_id` comes off the envelope rather than the payload: the
        stream id is what every statement here agrees on, and reading it
        from the payload would let a malformed row point one statement
        at a different walk than the other.

        `step_count` is stored rather than derived, because the list it
        counts is not in this table. It cannot change afterwards: no
        command adds a step to a walk.
        """
        payload: dict[str, Any] = event.payload
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            payload["reference_scheme"],
            payload["reference_value"],
            payload["procedure_name"],
            len(payload["steps"]),
            event.occurred_at,
        )

    async def _apply(
        self, event: StoredEvent, conn: ConnectionLike, sql: str, *args: object
    ) -> None:
        """Run one update, or say so when there is no row ahead of it.

        A step or an ending with no row means the genesis is missing,
        which the ordering guarantees cannot happen: events arrive in
        `(transaction_id, position)` order and a walk's own events share
        a stream. It is logged rather than raised because the
        alternative is wedging the whole projection over one walk, and a
        warning naming the walk is what an operator needs to rebuild it.
        """
        result = await conn.execute(sql, *args)
        if str(result).endswith(" 0"):
            _log.warning(
                "walk_summary.event_without_a_row",
                projection=PROJECTION_NAME,
                walk_id=str(event.stream_id),
                event_type=event.event_type,
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "STEP_EVENT_TYPES", "WalkSummaryProjection"]
