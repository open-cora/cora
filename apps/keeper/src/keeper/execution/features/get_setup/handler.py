"""Answer the question: authorize, fold the revisions, return the one asked for.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide.

Authorization still happens, and is not fenced by beamline, the way no
read here is. What values a beamline holds says how it runs a routine,
which a deployment should get to decide who may see.

`SetupNotFoundError` and `SetupRevisionNotFoundError` rather than a `None`
return. Both surfaces want a refusal, and raising the errors the writing
slices raise gets them mapped in one place instead of two. The two are
separate because the caller's next move differs: an unknown setup means a
wrong id, an unknown revision means a number past the latest, and the
second error says what the latest is.
"""

from typing import Protocol
from uuid import UUID

from keeper.execution.aggregates.setup import (
    Setup,
    SetupNotFoundError,
    SetupRevisionNotFoundError,
    load_setup_revisions,
)
from keeper.execution.features.get_setup.query import GetSetup
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "GetSetup"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetSetup,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Setup: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetSetup,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Setup:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_setup.denied",
                command_name=_COMMAND_NAME,
                setup_id=str(query.setup_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        revisions = await load_setup_revisions(deps.event_store, query.setup_id)
        if not revisions:
            raise SetupNotFoundError(query.setup_id)
        if query.revision is None:
            return revisions[-1]
        if not 1 <= query.revision <= len(revisions):
            raise SetupRevisionNotFoundError(query.setup_id, query.revision, len(revisions))
        return revisions[query.revision - 1]

    return handler


__all__ = ["Handler", "bind"]
