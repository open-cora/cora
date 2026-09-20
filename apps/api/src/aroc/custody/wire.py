"""Compose the Custody handlers from the process-wide dependencies.

`wire_custody(deps)` runs once during startup and the bundle it returns is
attached to the app. Routes and MCP tools both pull their handler out of
that bundle, which is what keeps the two surfaces calling the same code
rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   registering the same data twice
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

The read goes without the middle layer, because a read has nothing to
make idempotent. Tracing wraps both, because a query that is slow or
failing is as much a fact about the system as a write that is.

Registering a dataset takes the idempotency wrapper for the same reason
reporting a run does: the server mints the id, so a retry with no key
would leave a second record of one thing. That matters more here than it
looks. Nothing in this context refuses a duplicate on its own, because
one stream cannot see another, so the key is the only thing standing
between a redelivered report and two records of one body of data. A
producer that derives its key from the store's own address for the data
recomputes it after any restart having persisted nothing, which is what
makes at-least-once delivery safe.

No summary lookup is passed in, unlike the sibling context's wire module.
Nothing here lists yet. The query this context exists for, every dataset
a given run produced, needs a projection and a read port, and both arrive
with the slice that asks.
"""

from dataclasses import dataclass
from uuid import UUID

from aroc.custody.features import get_dataset, register_dataset
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.observability import with_tracing
from aroc.infrastructure.slices.idempotency import with_idempotency

_BC = "custody"


@dataclass(frozen=True)
class CustodyHandlers:
    """The bundle, one field per slice."""

    register_dataset: register_dataset.IdempotentHandler
    get_dataset: get_dataset.Handler


def wire_custody(deps: Kernel) -> CustodyHandlers:
    """Build the Custody handlers."""
    return CustodyHandlers(
        register_dataset=with_tracing(
            with_idempotency(
                register_dataset.bind(deps),
                deps.idempotency_store,
                command_name="RegisterDataset",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="RegisterDataset",
            bc=_BC,
        ),
        get_dataset=with_tracing(
            get_dataset.bind(deps),
            command_name="GetDataset",
            bc=_BC,
        ),
    )


__all__ = ["CustodyHandlers", "wire_custody"]
