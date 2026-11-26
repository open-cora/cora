"""Run the definition: authorize, load the operation, check the key, decide, append.

Create-style shape. A freshly minted id provably has no history, so this
handler skips the load-and-fold that an editing handler starts with and
hands `state=None` straight to the decider.

Fenced by the beamline the command names, the way a procedure's
definition is: the gate is asked about that beamline, so a grant for 19-BM
does not let a caller write 2-BM's values.

A setup for an operation that does not exist is refused here rather than
in the decider, because discovering the absence needs the store and the
decider has none. That is the split docs/reference/patterns.md draws
between a 404 and a refusal.

## The key is checked, not locked

A second setup under a key already held is refused, and the refusal rests
on asking `SetupSummaryLookup.find_setup` before the append. That is a
check and not a lock: an event-sourced aggregate has no consistency
boundary spanning its siblings, so nothing here can make the question and
the write one act.

Two windows are left open. Two definitions under one key arriving at once
both find the key free and both land. And in a deployment the lookup reads
a table a projection worker fills, so a definition made a moment ago may
not be in it yet, and a second one under the same key gets through. The
in-memory lookup folds the streams and has no such lag.

`Idempotency-Key` narrows the first window for a caller retrying its own
request and does nothing for two callers. What a race leaves behind is two
setups under one key, both in the log and both in a listing, and
`find_setup` answers with the first defined. The key index is not unique,
for the reason the projection module gives: a unique index would hide the
second rather than refuse it.

The name and the beamline are made into value objects here as well as in
the decider, because the lookup is asked in the form a row stores them. A
malformed one is refused here with the error the decider would have raised.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.operation import OperationNotFoundError, load_operation
from keeper.execution.aggregates.setup import (
    SETUP_STREAM_TYPE,
    SetupBeamline,
    SetupName,
    SetupSummaryLookup,
    to_payload,
)
from keeper.execution.features.define_setup.command import DefineSetup
from keeper.execution.features.define_setup.context import DefineSetupContext
from keeper.execution.features.define_setup.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "DefineSetup"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: DefineSetup,
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
        command: DefineSetup,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> UUID: ...


def bind(deps: Kernel, setups: SetupSummaryLookup) -> Handler:
    """Build the handler, closed over the dependencies and the read port.

    Two arguments, like the list slices, because the read port is not on
    the kernel and cannot be: the kernel is declared in infrastructure and
    a setup summary is Execution's own idea.
    """

    async def handler(
        command: DefineSetup,
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
            beamline=command.beamline,
        )
        if isinstance(decision, Deny):
            _log.info(
                "define_setup.denied",
                command_name=_COMMAND_NAME,
                beamline=command.beamline,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        operation = await load_operation(deps.event_store, command.operation_id)
        if operation is None:
            raise OperationNotFoundError(command.operation_id)

        existing = await setups.find_setup(
            beamline=SetupBeamline(command.beamline),
            operation_id=command.operation_id,
            name=SetupName(command.name),
        )

        new_id = deps.id_generator.new_id()
        now = deps.clock.now()
        events = decide(
            None,
            command,
            context=DefineSetupContext(
                operation=operation,
                existing_setup_id=existing.setup_id if existing is not None else None,
            ),
            now=now,
            new_id=new_id,
        )

        await deps.event_store.append(
            SETUP_STREAM_TYPE,
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
            "define_setup.success",
            command_name=_COMMAND_NAME,
            setup_id=str(new_id),
            beamline=command.beamline,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
