"""Run the report: authorize, load the plan, decide, append.

Create-style on its own stream, so there is no load-and-fold of a run and
`state=None` goes straight to the decider. What is new here is the load
of a DIFFERENT aggregate: the plan whose schema the parameters are
checked against.

That read is the first cross-aggregate load in this tree, and the shape
it follows is the one in docs/reference/patterns.md. The handler fetches
the sibling, refuses a missing one itself, and hands what it found to the
pure decider as a context value. The decider never sees a port.

Existence here, state in the decider. A plan id with no stream behind it
is a 404 raised from this function, because it means the caller named
something that does not exist. A plan that exists and forbids what was
asked would be a refusal from the decider; there is no such rule yet,
and the split is set up so that when one arrives it has somewhere to go.

One store is written. The plan is read and not touched, so there is no
ordering to get right and no window in which a crash leaves two streams
disagreeing.
"""

from typing import Protocol
from uuid import UUID

from aroc.execution.aggregates.plan import PlanNotFoundError, load_plan
from aroc.execution.aggregates.run import RUN_STREAM_TYPE, to_payload
from aroc.execution.errors import UnauthorizedError
from aroc.execution.features.report_run.command import ReportRun
from aroc.execution.features.report_run.context import ReportRunContext
from aroc.execution.features.report_run.decider import decide
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Deny
from aroc.infrastructure.slices.envelope import to_new_event
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "ReportRun"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: ReportRun,
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
        command: ReportRun,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
        idempotency_key: str | None = None,
    ) -> UUID: ...


def bind(deps: Kernel) -> Handler:
    """Build the handler, closed over the process-wide dependencies."""

    async def handler(
        command: ReportRun,
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
        )
        if isinstance(decision, Deny):
            _log.info(
                "report_run.denied",
                command_name=_COMMAND_NAME,
                plan_id=str(command.plan_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        plan = await load_plan(deps.event_store, command.plan_id)
        if plan is None:
            raise PlanNotFoundError(command.plan_id)

        new_id = deps.id_generator.new_id()
        now = deps.clock.now()
        events = decide(
            None,
            command,
            context=ReportRunContext(plan=plan),
            now=now,
            new_id=new_id,
        )

        await deps.event_store.append(
            RUN_STREAM_TYPE,
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
            "report_run.success",
            command_name=_COMMAND_NAME,
            run_id=str(new_id),
            plan_id=str(command.plan_id),
            external_ref_scheme=command.external_ref.scheme,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
