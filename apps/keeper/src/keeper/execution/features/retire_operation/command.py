"""The intent: stop offering this operation to be run."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class RetireOperation:
    """Stop offering this operation, because nothing answers to it any longer.

    Retire, not withdraw and not remove, for the reasons the device's
    retirement gives: withdraw is spoken for, and remove would claim the
    routine left the engine, which is a fact about somewhere else that
    this system was not present for. What this records is that this
    system no longer offers the routine, and that fact is made by the
    record rather than described by it.

    **There is no `occurred_at`**, which is R8 in
    docs/reference/naming.md. Retiring happens here, so the moment this
    system writes one is the moment it happened, and a supplied time
    would be fiction.

    No beamline either. An operation is one value for the whole facility,
    so retiring one reaches every beamline that cites it, and who may do
    that is the deployment's policy rather than a field here.
    """

    operation_id: UUID


__all__ = ["RetireOperation"]
