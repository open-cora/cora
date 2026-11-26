"""Keep `proj_execution_procedure_summary` in step with the procedure streams.

The Operation projection's sibling, and the same shape for the same reason:
two event types over two statements. The genesis inserts a row, active,
and the retirement moves it to retired.

## Running twice must be harmless

Delivery is at-least-once. The genesis takes `ON CONFLICT (procedure_id)
DO NOTHING`, and the retirement writes the same word every time, derived
from the event rather than from what the row holds, so applying either
twice is applying it once.

The execution summary is the projection in this context that could not do it
this way, because progress through an execution is not an absolute value. A
step count is: it is read off the genesis payload and every redelivery of
that row carries the same number.

## The status is derived here too

The event type decides the status, exactly as it does in the fold, and the
port contract suite pins the two together by running one set of assertions
against this table and against a fold over the same events.

## The name is three things at once

`proj_execution_procedure_summary` is the table, the bookmark row, and
this projection's registered name.
`test_projections_have_a_table_and_a_bookmark.py` is what makes the
agreement a rule rather than a habit.

## The steps are counted and not stored

A procedure may hold a thousand steps and a listing shows fifty
procedures. What the row carries is how long the routine is, which is the
question a list can answer usefully; the steps themselves are one call
away and the log has them either way.
"""

from typing import Any

from keeper.execution.aggregates.procedure.state import ProcedureStatus
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_execution_procedure_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "ProcedureDefined"
_RETIRED_EVENT_TYPE = "ProcedureRetired"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (procedure_id, name, beamline, step_count, status, created_at)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (procedure_id) DO NOTHING
"""

_RETIRE_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = $2
WHERE procedure_id = $1
"""

_log = get_logger(__name__)


class ProcedureSummaryProjection:
    """Folds procedure events into one row per procedure."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset({_GENESIS_EVENT_TYPE, _RETIRED_EVENT_TYPE})

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one event into the table, inside the worker's transaction.

        Raising rolls the whole batch back and leaves the bookmark where it
        was, so an event this cannot handle is retried forever rather than
        skipped. That is the right failure for a read model: stale and loud
        beats wrong and quiet.
        """
        if event.event_type == _GENESIS_EVENT_TYPE:
            payload: dict[str, Any] = event.payload
            steps: list[object] = payload["steps"]
            await conn.execute(
                _INSERT_SQL,
                event.stream_id,
                payload["procedure_name"],
                payload["beamline"],
                len(steps),
                ProcedureStatus.ACTIVE.value,
                event.occurred_at,
            )
            return
        await self._retire(event, conn)

    async def _retire(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Move an existing row to retired, or say so when there is none.

        A missing row means the genesis is missing, which the ordering
        guarantees cannot happen. It is logged rather than raised, for the
        reason the operation projection gives.
        """
        result = await conn.execute(_RETIRE_SQL, event.stream_id, ProcedureStatus.RETIRED.value)
        if isinstance(result, str) and result.endswith(" 0"):
            _log.warning(
                "procedure_summary.retirement_without_row",
                projection=PROJECTION_NAME,
                procedure_id=str(event.stream_id),
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "ProcedureSummaryProjection"]
