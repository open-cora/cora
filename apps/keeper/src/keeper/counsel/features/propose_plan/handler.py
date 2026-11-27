"""Propose the plan: authorize, load each operation, decide, append.

Create-style on its own stream, so there is no load-and-fold of a
proposal and `state=None` goes straight to the decider.

Each distinct operation the plan cites is loaded once and handed across
on a context, which is `define_procedure`'s shape for a procedure's runs.
One the plan cites that does not exist is refused here with Execution's
`OperationNotFoundError`, a 404, before anything is decided, so a plan is
never half checked: existence is the handler's to establish and state is
the decider's to judge, which is the split docs/reference/patterns.md
draws.

The principal becomes the proposer, exactly as it does for
`make_proposal`, and for the same reason.

Authorized as its own command rather than as `MakeProposal`. A plan is a
proposal, and a deployment that wants the two granted together grants
both; a gate that checked the other command's name would make one
permission mean two acts nobody could tell apart in a policy.
"""

from typing import Protocol
from uuid import UUID

from keeper.counsel.aggregates.proposal import PROPOSAL_STREAM_TYPE, to_payload
from keeper.counsel.features.propose_plan.command import ProposePlan
from keeper.counsel.features.propose_plan.context import ProposePlanContext
from keeper.counsel.features.propose_plan.decider import decide
from keeper.execution.aggregates.operation import (
    Operation,
    OperationNotFoundError,
    load_operation,
)
from keeper.infrastructure.kernel import Kernel
from keeper.infrastructure.logging import get_logger
from keeper.infrastructure.ports import Deny
from keeper.infrastructure.slices.envelope import to_new_event
from keeper.shared.reserved_ids import NIL_SENTINEL_ID
from keeper.shared.unauthorized import UnauthorizedError

_COMMAND_NAME = "ProposePlan"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: ProposePlan,
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
        command: ProposePlan,
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
        command: ProposePlan,
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
                "propose_plan.denied",
                command_name=_COMMAND_NAME,
                run_count=len(command.runs),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        operations: dict[UUID, Operation] = {}
        for run in command.runs:
            if run.operation_id in operations:
                continue
            operation = await load_operation(deps.event_store, run.operation_id)
            if operation is None:
                raise OperationNotFoundError(run.operation_id)
            operations[run.operation_id] = operation

        new_id = deps.id_generator.new_id()
        events = decide(
            None,
            command,
            context=ProposePlanContext(operations=operations),
            actor_id=principal_id,
            now=deps.clock.now(),
            new_id=new_id,
        )

        await deps.event_store.append(
            PROPOSAL_STREAM_TYPE,
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
            "propose_plan.success",
            command_name=_COMMAND_NAME,
            proposal_id=str(new_id),
            run_count=len(command.runs),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
