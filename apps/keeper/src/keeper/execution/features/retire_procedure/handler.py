"""Retire the procedure: load, authorize at its beamline, decide, append.

Update-style, so this command names a stream that already has a row. The
handler folds that history before deciding and passes the version it
read back as `expected_version`, so two callers retiring one procedure at
once produce one append and one `ConcurrencyError`, which surfaces as a
409, rather than a retirement the decider had no chance to refuse.

## Why the read comes before the gate

Every other handler here authorizes first. This one cannot and still be
fenced, because the beamline a procedure runs at is written on the
procedure and nowhere else, and a permission to retire 19-BM's routines
should not retire 2-BM's. So the procedure is read, an absent one is
refused, and the gate is asked with the beamline that was read.

What a refused caller learns before the gate is whether an id names a
procedure. That is the price of fencing by a fact the record holds
rather than one the caller asserts, and it is the smaller price: the
alternative was a beamline on the command, checked against the
procedure's, which asks every caller to repeat what the record already
says. `tests/architecture/test_beamline_commands_are_scoped.py` names
this slice as scoped by reading, so the beamline cannot quietly drop
out of the call.

No idempotency wrapper. A replayed call is already refused by the
domain, so the wrapper would be buying a nicer status code for a retry
rather than preventing a duplicate.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.procedure import (
    PROCEDURE_STREAM_TYPE,
    ProcedureNotFoundError,
    load_procedure_with_version,
    to_payload,
)
from keeper.execution.features.retire_procedure.command import RetireProcedure
from keeper.execution.features.retire_procedure.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "RetireProcedure"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: RetireProcedure,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: RetireProcedure,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None:
        state, version = await load_procedure_with_version(deps.event_store, command.procedure_id)
        if state is None:
            raise ProcedureNotFoundError(command.procedure_id)

        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
            beamline=state.beamline.value,
        )
        if isinstance(decision, Deny):
            _log.info(
                "retire_procedure.denied",
                command_name=_COMMAND_NAME,
                procedure_id=str(command.procedure_id),
                beamline=state.beamline.value,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        events = decide(state, command, now=deps.clock.now())

        await deps.event_store.append(
            PROCEDURE_STREAM_TYPE,
            command.procedure_id,
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
            "retire_procedure.success",
            command_name=_COMMAND_NAME,
            procedure_id=str(command.procedure_id),
            beamline=state.beamline.value,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["Handler", "bind"]
