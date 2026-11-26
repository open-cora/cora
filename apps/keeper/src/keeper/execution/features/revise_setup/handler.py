"""Revise the setup: load, authorize at its beamline, decide, append.

Update-style, so this command names a stream that already has rows.

## Two guards, over two windows

A revision is decided against what its caller read, and two windows open
between that read and the write. The command closes the first: it carries
the revision the caller read, and the decider refuses it unless that is
still the latest, naming both numbers. So a caller that fetched revision 2
while somebody else wrote revision 3 is told so, instead of landing its
values over 3's.

This handler closes the second. It folds the history before deciding and
passes the version it read back as `expected_version`, so two callers
revising one setup at the same moment, both from the latest revision,
produce one revision and one `ConcurrencyError`, which surfaces as a 409,
rather than two revisions numbered as though each had followed the same
one.

## Why the read comes before the gate

The beamline a setup belongs to is written on the setup and nowhere else,
and a permission to revise 19-BM's values should not revise 2-BM's. So
the setup is read, an absent one is refused, and the gate is asked with the
beamline that was read, which is the decision retiring a procedure made for
the same reason. `tests/architecture/test_beamline_commands_are_scoped.py`
names this slice as scoped by reading, so the beamline cannot quietly drop
out of the call.

What a refused caller learns before the gate is whether an id names a
setup. That is the price of fencing by a fact the record holds rather than
one the caller repeats.

## No idempotency wrapper

A replayed revision carries the revision number the first one was made
against, and the first one moved the setup past it, so the replay is
refused as stale by the domain rather than written twice. The wrapper
would buy a friendlier answer for a retry rather than prevent a duplicate.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.setup import (
    SETUP_STREAM_TYPE,
    SetupNotFoundError,
    load_setup_with_version,
    to_payload,
)
from keeper.execution.features.revise_setup.command import ReviseSetup
from keeper.execution.features.revise_setup.decider import decide
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "ReviseSetup"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies.

    Returns the number of the revision it wrote, which is the handle a
    caller reads that revision back by.
    """

    async def __call__(
        self,
        command: ReviseSetup,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> int: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: ReviseSetup,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> int:
        state, version = await load_setup_with_version(deps.event_store, command.setup_id)
        if state is None:
            raise SetupNotFoundError(command.setup_id)

        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
            beamline=state.beamline.value,
        )
        if isinstance(decision, Deny):
            _log.info(
                "revise_setup.denied",
                command_name=_COMMAND_NAME,
                setup_id=str(command.setup_id),
                beamline=state.beamline.value,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        events = decide(state, command, now=deps.clock.now())

        await deps.event_store.append(
            SETUP_STREAM_TYPE,
            command.setup_id,
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

        (revised,) = events
        _log.info(
            "revise_setup.success",
            command_name=_COMMAND_NAME,
            setup_id=str(command.setup_id),
            beamline=state.beamline.value,
            revision=revised.revision,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return revised.revision

    return handler


__all__ = ["Handler", "bind"]
