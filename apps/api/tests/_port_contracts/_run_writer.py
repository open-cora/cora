"""Append the run events the `RunSummaryLookup` contract reads back.

Shared by both drivers so the two sides of the contract are fed the same
rows. Only the reading differs: one driver folds the store the events went
into, the other advances a projection over them first.

Not a check and not a driver, so it sits beside the contract with a
leading underscore. `test_port_contracts_have_two_sides.py` counts every
module in this package as a contract and every file importing one as a
driver, and a helper counted as a contract would be one nothing drives.
"""

from datetime import datetime
from uuid import UUID, uuid4

from aroc.execution.aggregates.run.events import RunCompleted, RunReported, to_payload
from aroc.execution.aggregates.run.read import RUN_STREAM_TYPE
from aroc.infrastructure.ports.event_store import EventStore
from aroc.infrastructure.slices.envelope import to_new_event
from aroc.shared.identifier import Identifier


class EventStoreRunWriter:
    """Writes real run events, the way the two handlers do.

    Real events rather than rows, because the projection under test reads
    events and a contract fed seeded rows would agree about querying while
    saying nothing about whether the two sides read an event alike.
    """

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store
        self._principal_id = uuid4()

    async def report(
        self,
        *,
        run_id: UUID,
        plan_id: UUID,
        external_ref: Identifier,
        at: datetime,
    ) -> None:
        await self._append(
            run_id,
            expected_version=0,
            event=RunReported(
                run_id=run_id,
                plan_id=plan_id,
                parameters={},
                external_ref_scheme=external_ref.scheme,
                external_ref_value=external_ref.value,
                occurred_at=at,
            ),
            command_name="ReportRun",
        )

    async def complete(self, *, run_id: UUID, at: datetime) -> None:
        await self._append(
            run_id,
            expected_version=1,
            event=RunCompleted(run_id=run_id, occurred_at=at),
            command_name="CompleteRun",
        )

    async def _append(
        self,
        run_id: UUID,
        *,
        expected_version: int,
        event: RunReported | RunCompleted,
        command_name: str,
    ) -> None:
        await self._event_store.append(
            RUN_STREAM_TYPE,
            run_id,
            expected_version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=to_payload(event),
                    occurred_at=event.occurred_at,
                    event_id=uuid4(),
                    command_name=command_name,
                    correlation_id=uuid4(),
                    principal_id=self._principal_id,
                )
            ],
        )


__all__ = ["EventStoreRunWriter"]
