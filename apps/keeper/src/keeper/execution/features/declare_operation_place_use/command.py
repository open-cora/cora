"""The intent: say which of this operation's parameters name a place."""

from dataclasses import dataclass
from uuid import UUID

from keeper.execution.aggregates.operation import PlaceUse


@dataclass(frozen=True)
class DeclareOperationPlaceUse:
    """Declare, once, which parameters of a run of this operation name a place.

    Declare, for the reasons `DeclareOperationDeviceUse` gives for the same
    verb: a second declaration is refused whatever it says, and what it
    records is what the facility says of every run of the routine rather
    than a status somebody asserted.

    `place_use` arrives as its value object, so a parameter named twice is
    refused where the request is read rather than three layers in. Whether
    each parameter is one the operation takes needs the operation's
    schema, and the decider asks that.

    **There is no `occurred_at`**, which is R8 in docs/reference/naming.md.
    Declaring happens here.

    No beamline. An operation is one value for the whole facility, so a
    declaration decides which values in its runs are places at every
    beamline that runs it, and who may make one is the deployment's policy.
    """

    operation_id: UUID
    place_use: PlaceUse


__all__ = ["DeclareOperationPlaceUse"]
