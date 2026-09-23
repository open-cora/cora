"""Report one step: authorize, load, decide, append.

Update-style, so the walk is loaded with its version and the append is
made against it. That version is what makes two drivers reporting one
walk produce one append and one conflict rather than two outcomes for
one step.
"""

from typing import Protocol
from uuid import UUID

from aroc.execution.aggregates.walk import (
    WALK_STREAM_TYPE,
    load_walk_with_version,
    to_payload,
)
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.report_step.command import ReportWalkStep
from aroc.execution.features.report_step.decider import decide
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Deny
from aroc.infrastructure.slices.envelope import to_new_event
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ReportWalkStep"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: ReportWalkStep,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: ReportWalkStep,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "report_step.denied",
                command_name=_COMMAND_NAME,
                walk_id=str(command.walk_id),
                index=command.index,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        state, version = await load_walk_with_version(deps.event_store, command.walk_id)
        now = command.occurred_at if command.occurred_at is not None else deps.clock.now()
        events = decide(state, command, now=now)

        await deps.event_store.append(
            WALK_STREAM_TYPE,
            command.walk_id,
            version,
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
            "report_step.success",
            command_name=_COMMAND_NAME,
            walk_id=str(command.walk_id),
            index=command.index,
            outcome=str(command.outcome),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
