"""Run the registration: authorize, decide, append, then name.

Create-style shape. A freshly minted id provably has no history, so this
handler skips the load-and-fold that an update-style handler starts with
and hands `state=None` straight to the decider.

## Write order, and why this one

Two stores are written and they cannot be written together: the event
goes to the log, the display name goes to the profile table, and the
profile port takes no connection to share a transaction with. So one of
them lands first, and a crash in between leaves the other undone.

The event goes first. The two failures are not symmetrical:

    event first    a crash leaves an actor with no profile row. Reads
                   fall back to the tombstone. Visible, harmless, and
                   fixable by writing the name again.

    profile first  a crash leaves a profile row holding a person's name
                   under an id no event references. That is personal
                   data the ordinary erasure path cannot reach, because
                   erasure is asked for by actor and this actor does not
                   exist.

The whole reason the name lives outside the log is that personal data
has to be erasable. An ordering whose failure mode is unreachable
personal data gives that away to save a tombstone.

Closing the window entirely needs the profile port to accept a
connection, the way the erasure path already does, so both writes can
share one transaction. That is a port change, and it waits for a caller
that needs it rather than arriving on speculation.
"""

from typing import Protocol
from uuid import UUID

from aroc.access.aggregates.actor import (
    ACTOR_STREAM_TYPE,
    ActorName,
    to_payload,
)
from aroc.access.errors import UnauthorizedError
from aroc.access.features.register_actor.command import RegisterActor
from aroc.access.features.register_actor.decider import decide
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Deny, ProfileStore
from aroc.infrastructure.request import NIL_SENTINEL_ID
from aroc.infrastructure.slices.envelope import to_new_event

_COMMAND_NAME = "RegisterActor"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies.

    `causation_id` is the id of whatever triggered this command, when
    something did. An HTTP or MCP call is the root of its own chain and
    passes None; a future reaction to an event passes that event's id.
    """

    async def __call__(
        self,
        command: RegisterActor,
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
        command: RegisterActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> UUID: ...


def bind(deps: Kernel, *, profile_store: ProfileStore) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: RegisterActor,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> UUID:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            conduit_id=NIL_SENTINEL_ID,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "register_actor.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        new_id = deps.id_generator.new_id()
        now = deps.clock.now()
        events = decide(None, command, now=now, new_id=new_id)

        await deps.event_store.append(
            ACTOR_STREAM_TYPE,
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

        # After the append, so a crash here leaves a nameless actor rather
        # than an unreachable profile row. See the module docstring.
        await profile_store.upsert(
            actor_id=new_id,
            name=ActorName(command.name).value,
            created_at=now,
        )

        _log.info(
            "register_actor.success",
            command_name=_COMMAND_NAME,
            actor_id=str(new_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
