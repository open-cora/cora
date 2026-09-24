"""Answer the listing: authorize, then ask the read port.

No decider and no event store. This slice never folds a stream: the
question is which walk to name, and an event log answers that only if
something kept a summary as the events arrived.

The limit is clamped here rather than trusted, because both surfaces can
send one and only this side pays for it.
"""

from typing import Protocol
from uuid import UUID

from aroc.execution.aggregates.walk import WalkSummaryLookup, WalkSummaryPage
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.list_walks.query import MAX_PAGE_SIZE, ListWalks
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Deny
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ListWalks"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: ListWalks,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> WalkSummaryPage: ...


def bind(deps: Kernel, summaries: WalkSummaryLookup) -> Handler:
    """Build the handler, closed over the dependencies and the read port.

    Two arguments rather than one, for the reason `list_runs` takes two:
    the read port is not on the kernel and cannot be, because the kernel
    is declared in infrastructure and a walk summary is Execution's own
    idea. The wire module picks which implementation this gets.
    """

    async def handler(
        query: ListWalks,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> WalkSummaryPage:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "list_walks.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        return await summaries.list_walks(
            procedure_id=query.procedure_id,
            limit=min(query.limit, MAX_PAGE_SIZE),
            cursor=query.cursor,
        )

    return handler


__all__ = ["Handler", "bind"]
