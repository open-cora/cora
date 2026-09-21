"""Compose the Counsel handlers from the process-wide dependencies.

`wire_counsel(deps)` runs once during startup and the bundle it returns
is attached to the app. Routes and MCP tools both pull their handler out
of that bundle, which is what keeps the two surfaces calling the same
code rather than two copies of it.

Wrapping order, innermost first:

  1. bind          the bare handler
  2. idempotency   a replayed key returns the first answer instead of
                   making a second proposal
  3. tracing       one span per call, whether or not the key hit cache

Idempotency wraps inside tracing on purpose: a cache hit is still a call
somebody made and should still appear in a trace.

Only the genesis takes the middle layer. Making a proposal mints an id
on the server, so a retry with no key would leave a second record of one
piece of advice. Taking one goes without, because a replayed take is
already refused by the domain and the wrapper would buy a friendlier
status code rather than prevent a duplicate. The read goes without
because there is nothing in a read to make idempotent.

Nothing here takes more than the kernel. No slice reads a projection
yet, so there is no read adapter to pick and no startup failure to
declare, which is the one way this module is shorter than Custody's.
"""

from dataclasses import dataclass
from uuid import UUID

from aroc.counsel.features import get_proposal, make_proposal, take_proposal
from aroc.infrastructure.kernel import Kernel
from aroc.infrastructure.observability import with_tracing
from aroc.infrastructure.slices.idempotency import with_idempotency

_BC = "counsel"


@dataclass(frozen=True)
class CounselHandlers:
    """The bundle, one field per slice."""

    make_proposal: make_proposal.IdempotentHandler
    get_proposal: get_proposal.Handler
    take_proposal: take_proposal.Handler


def wire_counsel(deps: Kernel) -> CounselHandlers:
    """Build the Counsel handlers."""
    return CounselHandlers(
        make_proposal=with_tracing(
            with_idempotency(
                make_proposal.bind(deps),
                deps.idempotency_store,
                command_name="MakeProposal",
                serialize_result=str,
                deserialize_result=lambda raw: UUID(str(raw)),
                lock_stale_seconds=deps.settings.idempotency_lock_stale_seconds,
            ),
            command_name="MakeProposal",
            bc=_BC,
        ),
        get_proposal=with_tracing(
            get_proposal.bind(deps),
            command_name="GetProposal",
            bc=_BC,
        ),
        take_proposal=with_tracing(
            take_proposal.bind(deps),
            command_name="TakeProposal",
            bc=_BC,
        ),
    )


__all__ = ["CounselHandlers", "wire_counsel"]
