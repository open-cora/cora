"""LogbookMirror: pluggable mirror for agent-emitted Decisions.

Defines the abstract Protocol; NO production implementor lands yet.
The first concrete implementor is deferred until a pilot facility
wires its operator logbook (Olog at APS; SciLog at PSI; SciCat at
ESS / DESY / MAX IV).

## Why a port without an implementor

The RunDebriefer design (the design notes lock #45)
identified the operator-logbook mirror as a likely but
under-validated extension. Defining the port now without an
adapter:

  - Reserves the conceptual slot in the `Kernel` (one Optional
    field) so the subscriber's wiring shape is final.
    Adding the adapter later doesn't churn the subscriber code
    or the wire-up.
  - Documents the intended seam for cross-BC / cross-facility
    integration so a contributor adding `PhoebusOlogAdapter`
    doesn't have to re-derive the API shape from the design memo.
  - Keeps SciLog and SciCat as adapter swaps (not new ports) per
    the design lock: "SciLogMirrorPort and SciCatMirrorPort are
    not separate ports; they are alternate implementors of
    `LogbookMirror`."

The `Kernel.logbook_mirror` field is typed `LogbookMirror |
None` with a `None` default; the subscriber treats `None` as
"mirror disabled" and skips the call. No-op today; observable
extension point once an adapter lands.

## Call shape

`mirror_decision(decision_id, narrative, target_logbook)` is
fire-and-forget from the subscriber's perspective: the mirror
adapter handles its own retries / timeouts / error logging. The
return type is `None` rather than a status code because the
Decision is the audit-grade source of truth; the mirror is a
convenience surface and its failure must not propagate to the
subscriber's Decision-emission path. Adapters that need richer
error reporting can structure-log via `structlog` directly.
"""

from typing import Protocol
from uuid import UUID


class LogbookMirror(Protocol):
    """Optional mirror that pushes agent-emitted Decisions to an
    operator-facing logbook system (Olog / SciLog / SciCat).

    Single implementor per deployment when wired; `None` today
    (no implementor exists yet). The RunDebriefer subscriber checks
    `kernel.logbook_mirror is not None` before calling.
    """

    async def mirror_decision(
        self,
        *,
        decision_id: UUID,
        narrative: str,
        target_logbook: str,
    ) -> None:
        """Mirror an agent-emitted Decision narrative to an operator logbook.

        `decision_id` is the Decision aggregate identity so the
        mirrored entry can backlink (typically rendered as a URL
        into the AROC UI).

        `narrative` is the human-readable text payload (the BLUF +
        4-section AAR for RunDebriefer). The adapter SHOULD NOT
        re-render or reformat; the subscriber passes a fully
        formed string.

        `target_logbook` selects WHERE in the destination system
        the entry lands: a named logbook, an instrument identifier, or
        whatever the destination uses to route. The subscriber derives
        it from the originating aggregate's own binding or from config;
        this port does not care which.

        Errors are the adapter's responsibility to log; this method
        MUST NOT raise to the caller. The Decision aggregate write
        is the source of truth and must not depend on logbook
        availability.
        """
        ...


__all__ = ["LogbookMirror"]
