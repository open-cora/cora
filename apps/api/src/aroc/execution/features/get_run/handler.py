"""Answer the question: authorize, load, return.

No decider, no append, no clock. A read produces no events, so there is
nothing for a pure decision function to decide and nothing to make
reproducible on replay.

Authorization still happens. A run record says what was run and with
what, which is a description of activity rather than of configuration, so
who may read one is a question a deployment should get to answer.

`RunNotFoundError` rather than a `None` return. The aggregate's `load_run`
returns None and leaves the meaning to its caller, which is this handler:
both surfaces want a refusal, and raising the same error the writing
slice's sibling raises gets it mapped in one place instead of two.
"""

from typing import Protocol
from uuid import UUID

from aroc.execution.aggregates.run import Run, RunNotFoundError, load_run
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.get_run.query import GetRun
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Deny
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "GetRun"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        query: GetRun,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Run: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        query: GetRun,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> Run:
        _ = causation_id
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=_COMMAND_NAME,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            _log.info(
                "get_run.denied",
                command_name=_COMMAND_NAME,
                run_id=str(query.run_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        run = await load_run(deps.event_store, query.run_id)
        if run is None:
            raise RunNotFoundError(query.run_id)
        return run

    return handler


__all__ = ["Handler", "bind"]
