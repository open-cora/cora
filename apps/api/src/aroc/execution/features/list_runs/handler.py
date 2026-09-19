"""Answer the question: authorize, clamp, read the summaries.

No decider, no append, no clock, the same as the other two reads. What is
different is where the answer comes from: `get_run` folds a stream, and
this reads a table a projection maintains, through a port so that the
environment with no database can answer too.

Authorization is the same gate the single read uses, and for the same
reason: a list of runs says what has been run and when, which is a
description of activity. Which runs a given principal may see is a
narrower question that needs per-row scoping, and that is deferred with
the rest of it.

The limit is clamped rather than refused. A caller asking for two hundred
rows has not done anything wrong, they have asked for more than this
server hands out at once, and the honest answer is a hundred rows and a
cursor rather than a 400 and no data.
"""

from typing import Protocol
from uuid import UUID

from aroc.execution.aggregates.run.summary import RunSummaryLookup, RunSummaryPage
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.list_runs.query import MAX_PAGE_SIZE, ListRuns
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Deny
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ListRuns"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: ListRuns,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> RunSummaryPage: ...


def bind(deps: Kernel, summaries: RunSummaryLookup) -> Handler:
    """Build the handler, closed over the dependencies and the read port.

    Two arguments rather than one. Every other slice in this context takes
    the kernel alone, because everything it needs is on the kernel; the
    read port is not, and cannot be, because the kernel is declared in
    infrastructure and a run summary is Execution's own idea. The wire
    module picks which implementation this gets.
    """

    async def handler(
        query: ListRuns,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> RunSummaryPage:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "list_runs.denied",
                command_name=_COMMAND_NAME,
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        return await summaries.list_runs(
            external_ref=query.external_ref,
            limit=min(query.limit, MAX_PAGE_SIZE),
            cursor=query.cursor,
        )

    return handler


__all__ = ["Handler", "bind"]
