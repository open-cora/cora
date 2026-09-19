"""Keep `proj_execution_run_summary` in step with the run streams.

The first projection in this repository. The machinery it plugs into came
with the chassis and has never had a subscriber; what follows is the whole
of what a bounded context has to supply: a name, the event types to hear
about, and what to do with one.

## The name is three things at once

`proj_execution_run_summary` is the table, the bookmark row, and this
projection's registered name. They have to agree, because the worker finds
the bookmark by the name and the SQL below finds the table by spelling it,
and `test_projections_have_a_table_and_a_bookmark.py` is what makes the
agreement a rule rather than a habit.

## Running twice must be harmless

Delivery is at-least-once. The worker advances its bookmark in the same
transaction as the writes, so a crash between the two replays the batch,
and a replayed batch has to leave the table where the first pass left it.

The genesis takes `ON CONFLICT (run_id) DO NOTHING`: a run's first event
arriving twice is the same row twice, and the second changes nothing. The
transitions are plain updates that set a status to a value derived from
the event type, so applying one twice writes the same value twice.

`created_at` is deliberately not touched by a transition. It is the one
column a replay could corrupt, because a later event replayed onto an
existing row would otherwise overwrite when the run started with when it
ended.

## What a duplicated external reference does

Nothing. There is no unique index on the reference pair, so two records of
one engine run make two rows and a caller filtering on the reference sees
both. The alternative, a unique index, enforces uniqueness by dropping the
second row here, which would leave a run that exists in the log missing
from every listing. A read model that undercounts is worse than one that
shows the caller the duplicate and lets them deal with it.
"""

from typing import Any
from uuid import UUID

from aroc.execution.aggregates.run.state import RunStatus
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports.event_store import StoredEvent
from aroc.infrastructure.projection.subscriber import ConnectionLike

_log = get_logger(__name__)

PROJECTION_NAME = "proj_execution_run_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "RunReported"

STATUS_BY_EVENT_TYPE: dict[str, RunStatus] = {
    "RunCompleted": RunStatus.COMPLETED,
    "RunAborted": RunStatus.ABORTED,
    "RunFailed": RunStatus.FAILED,
    "RunPaused": RunStatus.PAUSED,
    "RunResumed": RunStatus.RUNNING,
}
"""Which status each transition leaves the run in.

Public because the check that keeps it honest lives in another module. A
mapping only this file can read is a mapping only this file can be wrong
about.

The same mapping the evolver applies to state, written again because the
evolver folds typed events and this reads stored rows, and because a
projection that imported the evolver would have to rebuild the whole
stream to learn one value it already has.

`test_the_projection_and_the_evolver_agree_on_every_status` is the guard
against the two drifting.
"""

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (
    run_id, plan_id, external_ref_scheme, external_ref_value,
    status, created_at, updated_at
) VALUES ($1, $2, $3, $4, $5, $6, $6)
ON CONFLICT (run_id) DO NOTHING
"""

_UPDATE_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = $2, updated_at = $3
WHERE run_id = $1
"""


class RunSummaryProjection:
    """Folds run events into one row per run."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset(
        {_GENESIS_EVENT_TYPE, *STATUS_BY_EVENT_TYPE},
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
        await self._transition(event, conn)

    async def _insert(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write the genesis row.

        `plan_id` is parsed back into a UUID because a payload holds
        primitives and the column holds a uuid. `run_id` comes off the
        envelope rather than the payload: the stream id is what the two
        SQL statements agree on, and reading it from the payload would
        let a malformed row point one statement at a different run than
        the other.
        """
        payload: dict[str, Any] = event.payload
        await conn.execute(
            _INSERT_SQL,
            event.stream_id,
            UUID(payload["plan_id"]),
            payload["external_ref_scheme"],
            payload["external_ref_value"],
            str(RunStatus.RUNNING),
            event.occurred_at,
        )

    async def _transition(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Move an existing row's status, or say so when there is none.

        A transition with no row ahead of it means the genesis is missing,
        which the ordering guarantees cannot happen: events arrive in
        `(transaction_id, position)` order and a run's own events share a
        stream. It is logged rather than raised because the alternative is
        wedging the whole projection over one run, and a warning that says
        which run is what an operator needs to rebuild it.
        """
        status = STATUS_BY_EVENT_TYPE[event.event_type]
        result = await conn.execute(
            _UPDATE_SQL,
            event.stream_id,
            str(status),
            event.occurred_at,
        )
        if str(result).endswith(" 0"):
            _log.warning(
                "run_summary.transition_without_a_row",
                projection=PROJECTION_NAME,
                run_id=str(event.stream_id),
                event_type=event.event_type,
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "STATUS_BY_EVENT_TYPE", "RunSummaryProjection"]
