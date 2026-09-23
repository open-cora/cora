"""Report the walk: authorize, decide, append.

Create-style on its own stream, so there is no load-and-fold of a walk
and `state=None` goes straight to the decider.

No context module, unlike `report_run` next door. That slice loads the
plan because its decision reads the plan's schema. A walk cites nothing:
it declares its own steps, so there is no sibling stream to read and
nothing to hand across.
"""

from typing import Protocol
from uuid import UUID

from aroc.execution.aggregates.walk import WALK_STREAM_TYPE, to_payload
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.report_walk.command import ReportWalk
from aroc.execution.features.report_walk.decider import decide
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Deny
from aroc.infrastructure.slices.envelope import to_new_event
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ReportWalk"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: ReportWalk,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID: ...


class IdempotentHandler(Protocol):
    """The same handler once the idempotency wrapper is around it.

    One extra keyword. None means behave exactly like the bare handler,
    which is what every caller without a retry key gets.
    """

    async def __call__(
        self,
        command: ReportWalk,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> UUID: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: ReportWalk,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "report_walk.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        new_id = deps.id_generator.new_id()
        now = command.occurred_at if command.occurred_at is not None else deps.clock.now()
        events = decide(None, command, now=now, new_id=new_id)

        await deps.event_store.append(
            WALK_STREAM_TYPE,
            new_id,
            0,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=to_payload(event),
                    occurred_at=event.occurred_at,
                    event_id=deps.id_generator.new_id(),
                    command_name=_COMMAND_NAME,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    principal_id=principal_id,
                )
                for event in events
            ],
        )

        _log.info(
            "report_walk.success",
            command_name=_COMMAND_NAME,
            walk_id=str(new_id),
            step_count=len(command.steps),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
