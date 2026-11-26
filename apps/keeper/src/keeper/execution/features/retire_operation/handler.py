"""Retire the operation: authorize, load, decide, append.

Update-style, so this command names a stream that already has a row. The
handler folds that history before deciding and passes the version it
read back as `expected_version`, so two callers retiring one operation at
once produce one append and one `ConcurrencyError`, which surfaces as a
409, rather than a retirement the decider had no chance to refuse.

No idempotency wrapper. A replayed call is already refused by the
domain, so the wrapper would be buying a nicer status code for a retry
rather than preventing a duplicate. See the wiring module, which says
which layers a slice gets and why.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.operation import (
    OPERATION_STREAM_TYPE,
    load_operation_with_version,
    to_payload,
)
from keeper.execution.features.retire_operation.command import RetireOperation
from keeper.execution.features.retire_operation.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "RetireOperation"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: RetireOperation,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: RetireOperation,
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
                "retire_operation.denied",
                command_name=_COMMAND_NAME,
                operation_id=str(command.operation_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        state, version = await load_operation_with_version(deps.event_store, command.operation_id)
        events = decide(state, command, now=deps.clock.now())

        await deps.event_store.append(
            OPERATION_STREAM_TYPE,
            command.operation_id,
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
            "retire_operation.success",
            command_name=_COMMAND_NAME,
            operation_id=str(command.operation_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
