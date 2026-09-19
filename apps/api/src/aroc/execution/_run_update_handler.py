"""The shared shell behind every command that moves an existing run.

Five slices append to a stream that already has rows: the three endings
and the two halves of the pause cycle. Each one authorizes, loads and
folds, decides, appends at the version it read, and logs. Only three
things differ between them, and this factory takes exactly those three.

Hoisted at five, where `docs/reference/layout.md` says three. It was
deferred twice on purpose. The five copies were guarded by
`test_handlers_authorize_their_own_command.py`, which required an
authorize call inside each slice's own handler and was the thing standing
between a copied slice and a silently wrong gate. Hoisting moves that
call in here, so the guard had to learn to follow the delegation first.
It now checks that a slice passes its own `_COMMAND_NAME` to exactly one
call, and that whatever this module does with the name reaches the gate.

## What stays in the slice

`_COMMAND_NAME`, the decider, the `Handler` protocol and the logger. The
constant stays because three other fitness checks read it out of the
slice's handler module: the wire label agreeing with it, the governing
command list deriving from it, and the gate check above. The logger stays
so a log line still names the slice that wrote it rather than this file.

## Why the types here are private

The module-naming rule reads public classes and expects them to be named
after their file. A module with none is a function namespace, which is
what this is: the protocols below describe one function's arguments and
its result, not the point of the module. Each slice keeps its own public
`Handler`, and the generic returned here satisfies it structurally.
"""

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

import structlog

from aroc.execution.aggregates.run import (
    RUN_STREAM_TYPE,
    Run,
    RunEvent,
    load_run_with_version,
    to_payload,
)
from aroc.execution.errors import UnauthorizedError
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.ports import Deny
from aroc.infrastructure.slices.envelope import to_new_event
from aroc.shared.reserved_ids import NIL_SENTINEL_ID


class _RunUpdateCommand(Protocol):
    """Any command naming a run that already exists.

    One attribute, because that is all the shell touches. Everything a
    command carries beyond the id is the decider's business, and the
    decider is supplied by the slice that knows the concrete type.
    """

    @property
    def run_id(self) -> UUID: ...


class _Decide[C: _RunUpdateCommand](Protocol):
    """A slice's pure decision function, as this shell calls it."""

    def __call__(self, state: Run | None, command: C, *, now: datetime) -> Sequence[RunEvent]: ...


class _Handler[C: _RunUpdateCommand](Protocol):
    """What a slice's `bind` hands back, before the wire module wraps it."""

    async def __call__(
        self,
        command: C,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None: ...


def _log_event_prefix(command_name: str) -> str:
    """`CompleteRun` to `complete_run`, for the log event name.

    Derived rather than passed, so the name on a log line and the name at
    the gate cannot drift apart. It was a second string in each of the
    five copies, which is one more place a copied slice could keep its
    neighbour's name.
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", command_name).lower()


def bind_run_update[C: _RunUpdateCommand](
    deps: Kernel,
    *,
    command_name: str,
    decide: _Decide[C],
    log: structlog.stdlib.BoundLogger,
) -> _Handler[C]:
    """Build the handler for one command that moves an existing run.

    The version read alongside the state is the whole of the concurrency
    story. Two callers moving the same run at once both fold the same
    state and both decide to append at that version; the store lets one
    through and raises `ConcurrencyError` at the other, which surfaces as
    a 409. Without it the second append would land as a second move on a
    run that had already made it, which every decider here exists to
    refuse.

    No idempotency wrapper on any of the five. A replayed move is already
    refused by the domain, so the wrapper would buy a friendlier status
    code for a retry rather than prevent a duplicate. See the wiring
    module, which says which layers a slice gets and why.
    """
    prefix = _log_event_prefix(command_name)

    async def handler(
        command: C,
        *,
        principal_id: UUID,
        correlation_id: UUID,
        causation_id: UUID | None = None,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> None:
        decision = await deps.authz.authorize(
            principal_id=principal_id,
            command_name=command_name,
            surface_id=surface_id,
        )
        if isinstance(decision, Deny):
            log.info(
                f"{prefix}.denied",
                command_name=command_name,
                run_id=str(command.run_id),
                principal_id=str(principal_id),
                correlation_id=str(correlation_id),
                reason=decision.reason,
            )
            raise UnauthorizedError(decision.reason)

        state, version = await load_run_with_version(deps.event_store, command.run_id)
        now = deps.clock.now()
        events = decide(state, command, now=now)

        await deps.event_store.append(
            RUN_STREAM_TYPE,
            command.run_id,
            version,
            [
                to_new_event(
                    event_type=type(event).__name__,
                    payload=to_payload(event),
                    occurred_at=event.occurred_at,
                    event_id=deps.id_generator.new_id(),
                    command_name=command_name,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                    principal_id=principal_id,
                )
                for event in events
            ],
        )

        log.info(
            f"{prefix}.success",
            command_name=command_name,
            run_id=str(command.run_id),
            principal_id=str(principal_id),
            correlation_id=str(correlation_id),
        )

    return handler


__all__ = ["bind_run_update"]
