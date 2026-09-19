"""Compose the Execution handlers from the process-wide dependencies.

`wire_execution(deps)` runs once during startup and the bundle it returns
is attached to the app. Routes and MCP tools both pull their handler out
of that bundle, which is what keeps the two surfaces calling the same
code rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   defining a second plan
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

`get_plan` goes without the middle layer, because a read has nothing to
make idempotent. Tracing wraps both. A query that is slow or failing is
as much a fact about the system as a write that is.
"""

from dataclasses import dataclass
from uuid import UUID

from aroc.execution.features import define_plan, get_plan
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.observability import with_tracing
from aroc.infrastructure.slices.idempotency import with_idempotency

_BC = "execution"


@dataclass(frozen=True)
class ExecutionHandlers:
    """The bundle, one field per slice."""

    define_plan: define_plan.IdempotentHandler
    get_plan: get_plan.Handler


def wire_execution(deps: Kernel) -> ExecutionHandlers:
    """Build the Execution handlers."""
    return ExecutionHandlers(
        define_plan=with_tracing(
            with_idempotency(
                define_plan.bind(deps),
                deps.idempotency_store,
                command_name="DefinePlan",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="DefinePlan",
            bc=_BC,
        ),
        get_plan=with_tracing(
            get_plan.bind(deps),
            command_name="GetPlan",
            bc=_BC,
        ),
    )


__all__ = ["ExecutionHandlers", "wire_execution"]
