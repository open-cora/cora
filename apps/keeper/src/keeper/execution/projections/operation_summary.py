"""Keep `proj_execution_operation_summary` in step with the operation streams.

The Execution projection's sibling, and much the smaller of the two: three
event types over three statements. The genesis inserts a row, active and
undeclared, a declaration of device use writes the value it carries, and
the retirement moves the row to retired. Nothing else happens to an
operation, so nothing else is written.

## Running twice must be harmless

Delivery is at-least-once. The worker advances its bookmark in the same
transaction as the writes, so a crash between the two replays the batch.

The genesis takes `ON CONFLICT (operation_id) DO NOTHING`. The other two
are idempotent for a different reason: each writes the same value every
time, derived from the event rather than from what the row holds, so
applying one twice is applying it once.

## The status is derived here too

The event type decides the status, exactly as it does in the fold. That
is the same derivation written a second time, in a second language, and
the port contract suite is what pins the two together: it runs one set of
assertions against this table and against a fold over the same events.

## The name is three things at once

`proj_execution_operation_summary` is the table, the bookmark row, and this
projection's registered name. `test_projections_have_a_table_and_a_bookmark.py`
is what makes the agreement a rule rather than a habit.

## Two operations may share a name and both rows stay

There is no unique index on the name, deliberately, because the aggregate
says two operations may carry one name on purpose. A unique index here would
drop the second, which would hide an operation that exists in the log from
every listing and from the caller most likely to be confused by it.
"""

from typing import Any

from keeper.execution.aggregates.operation.state import OperationStatus
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports.event_store import StoredEvent
from keeper.infrastructure.projection.subscriber import ConnectionLike

PROJECTION_NAME = "proj_execution_operation_summary"
"""The table, the bookmark row, and the registered name.

One constant because the three must match and they are read in three
different places: the migration that creates the table, the worker that
reads the bookmark, and the adapter that queries the rows.
"""

_GENESIS_EVENT_TYPE = "OperationDefined"
_DECLARED_EVENT_TYPE = "OperationDeviceUseDeclared"
_RETIRED_EVENT_TYPE = "OperationRetired"

_INSERT_SQL = f"""
INSERT INTO {PROJECTION_NAME} (operation_id, name, status, drives_devices, created_at)
VALUES ($1, $2, $3, NULL, $4)
ON CONFLICT (operation_id) DO NOTHING
"""

_DECLARE_SQL = f"""
UPDATE {PROJECTION_NAME}
SET drives_devices = $2
WHERE operation_id = $1
"""

_RETIRE_SQL = f"""
UPDATE {PROJECTION_NAME}
SET status = $2
WHERE operation_id = $1
"""

_log = get_logger(__name__)


class OperationSummaryProjection:
    """Folds operation events into one row per operation."""

    name = PROJECTION_NAME
    subscribed_event_types = frozenset(
        {_GENESIS_EVENT_TYPE, _DECLARED_EVENT_TYPE, _RETIRED_EVENT_TYPE}
    )

    async def apply(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write one event into the table, inside the worker's transaction.

        Raising rolls the whole batch back and leaves the bookmark where it
        was, so an event this cannot handle is retried forever rather than
        skipped. That is the right failure for a read model: stale and loud
        beats wrong and quiet.
        """
        if event.event_type == _GENESIS_EVENT_TYPE:
            payload: dict[str, Any] = event.payload
            await conn.execute(
                _INSERT_SQL,
                event.stream_id,
                payload["operation_name"],
                OperationStatus.ACTIVE.value,
                event.occurred_at,
            )
            return
        if event.event_type == _DECLARED_EVENT_TYPE:
            await self._declare(event, conn)
            return
        await self._retire(event, conn)

    async def _declare(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Write the declared device use onto an existing row, or say so when there is none.

        A missing row is logged rather than raised, for the reason the
        retirement below gives.
        """
        payload: dict[str, Any] = event.payload
        result = await conn.execute(_DECLARE_SQL, event.stream_id, payload["drives_devices"])
        if isinstance(result, str) and result.endswith(" 0"):
            _log.warning(
                "operation_summary.declaration_without_row",
                projection=PROJECTION_NAME,
                operation_id=str(event.stream_id),
                position=event.position,
            )

    async def _retire(self, event: StoredEvent, conn: ConnectionLike) -> None:
        """Move an existing row to retired, or say so when there is none.

        A missing row means the genesis is missing, which the ordering
        guarantees cannot happen: events arrive in `(transaction_id,
        position)` order and an operation's own events share a stream. It
        is logged rather than raised, for the reason the device projection
        gives: wedging every listing over one operation is worse than a
        warning naming it.
        """
        result = await conn.execute(_RETIRE_SQL, event.stream_id, OperationStatus.RETIRED.value)
        if isinstance(result, str) and result.endswith(" 0"):
            _log.warning(
                "operation_summary.retirement_without_row",
                projection=PROJECTION_NAME,
                operation_id=str(event.stream_id),
                position=event.position,
            )


__all__ = ["PROJECTION_NAME", "OperationSummaryProjection"]
