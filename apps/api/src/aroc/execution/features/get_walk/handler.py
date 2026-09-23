"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide.

Authorization still happens. A walk record says what was driven and how
each step of it went, which is a description of activity rather than of
configuration, so who may read one is a question a deployment should get
to answer.

`WalkNotFoundError` rather than a `None` return. The aggregate's
`load_walk` returns None and leaves the meaning to its caller, which is
this handler: both surfaces want a refusal, and raising the same error
the writing slices raise gets it mapped in one place instead of two.
"""

from typing import Protocol
from uuid import UUID

from aroc.execution.aggregates.walk import Walk, WalkNotFoundError, load_walk
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.get_walk.query import GetWalk
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Deny
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetWalk"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetWalk,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Walk: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetWalk,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Walk:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_walk.denied",
                command_name=_COMMAND_NAME,
                walk_id=str(query.walk_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        walk = await load_walk(deps.event_store, query.walk_id)
        if walk is None:
            raise WalkNotFoundError(query.walk_id)
        return walk

    return handler


__all__ = ["Handler", "bind"]
