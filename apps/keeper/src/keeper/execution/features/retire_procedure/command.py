"""The intent: stop handing this procedure out."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RetireProcedure:
    """Stop handing this procedure out, because nothing will drive it any longer.

    Retire, not withdraw and not remove, for the reasons the device's
    retirement gives. What this records is that this system no longer
    hands the routine out, and that fact is made by the record rather
    than described by it.

    **There is no `occurred_at`**, which is R8 in
    docs/reference/naming.md: retiring happens here, so a supplied time
    would be fiction.

    **There is no beamline**, although the procedure has one and the
    retirement is authorized against it. The beamline is the procedure's
    own fact, written on its genesis, so the handler reads it there. A
    field here would ask every caller to repeat what the record already
    holds, and its only possible effect would be a refusal when the two
    disagreed.
    """

    procedure_id: UUID


__all__ = ["RetireProcedure"]
