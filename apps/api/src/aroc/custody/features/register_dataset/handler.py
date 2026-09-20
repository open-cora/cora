"""Run the registration: authorize, check the run, decide, append.

Create-style on its own stream, so there is no load-and-fold of a dataset
and `state=None` goes straight to the decider.

The run is loaded and then only tested for existence. That is the second
cross-aggregate load in this tree and the first that crosses a bounded
context, so the shape is worth being explicit about: the handler fetches
the sibling, refuses a missing one itself, and passes nothing across to
the decision. `report_run` builds a context dataclass because its decider
reads the plan's schema; this one has nothing to read, so there is no
context to build.

`RunNotFoundError` is Execution's class, raised from here. It is not
re-registered on Custody's routes: FastAPI's exception handlers are
app-scoped and Execution already maps it to 404, which is the rule in
docs/reference/patterns.md for a cross-BC domain error.

The run is read and not touched, so one store is written, there is no
ordering to get right, and no window in which a crash leaves two streams
disagreeing. The read can be stale by the time the append lands, which is
accepted for the usual reason: what this check is for is catching a
caller who named the wrong run, not racing one being reported.
"""

from typing import Protocol
from uuid import UUID

from aroc.custody.aggregates.dataset import DATASET_STREAM_TYPE, to_payload
from aroc.custody.errors import UnauthorizedError
from aroc.custody.features.register_dataset.command import RegisterDataset
from aroc.custody.features.register_dataset.decider import decide
from aroc.execution.aggregates.run import RunNotFoundError, load_run
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Deny
from aroc.infrastructure.slices.envelope import to_new_event
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_COMMAND_NAME = "RegisterDataset"

_log = get_logger(__name__)


class Handler(Protocol):
    """The bare handler, before the wrapping the wire module applies."""

    async def __call__(
        self,
        command: RegisterDataset,
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
        command: RegisterDataset,
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
        command: RegisterDataset,
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
                "register_dataset.denied",
                command_name=_COMMAND_NAME,
                run_id=str(command.run_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        run = await load_run(deps.event_store, command.run_id)
        if run is None:
            raise RunNotFoundError(command.run_id)

        new_id = deps.id_generator.new_id()
        now = command.occurred_at if command.occurred_at is not None else deps.clock.now()
        events = decide(None, command, now=now, new_id=new_id)

        await deps.event_store.append(
            DATASET_STREAM_TYPE,
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
            "register_dataset.success",
            command_name=_COMMAND_NAME,
            dataset_id=str(new_id),
            run_id=str(command.run_id),
            external_ref_scheme=command.external_ref.scheme,
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )
        return new_id

    return handler


__all__ = ["Handler", "IdempotentHandler", "bind"]
