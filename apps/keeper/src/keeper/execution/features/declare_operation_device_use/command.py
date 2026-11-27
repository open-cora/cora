"""The intent: say whether a run of this operation drives devices."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class DeclareOperationDeviceUse:
    """Declare, once, whether a run of this operation drives devices where it runs.

    Declare, not set and not mark. Setting reads as a value that can be set
    again, and this cannot: a second declaration is refused whichever way
    it points, and a wrong one is corrected by defining another operation.
    Marking is the event shape this tree keeps for a status somebody
    asserted, and this is not a status: it is what the facility says every
    run of the routine does.

    The command name carries the aggregate and the sub-concept both, which
    is what lets its event read as one fact on the operation's stream. The
    slice and the tool carry them too, the way `retire_operation` carries
    its subject, because the verb acts on the operation itself.

    **There is no `occurred_at`**, which is R8 in docs/reference/naming.md.
    Declaring happens here, so the moment this system writes it is the
    moment it was declared.

    No beamline. An operation is one value for the whole facility, so a
    declaration decides the claims of its runs at every beamline that runs
    it, and who may make one is the deployment's policy rather than a
    field here.
    """

    operation_id: UUID
    drives_devices: bool


__all__ = ["DeclareOperationDeviceUse"]
