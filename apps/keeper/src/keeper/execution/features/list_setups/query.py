"""The question: which setups, newest first, and where do I carry on from?

`GetSetup` names the setup it wants. This one is asking which setup to
name, which a fold cannot answer: it would mean replaying every setup
stream to see which ones match.

Three optional filters, the three parts of a setup's key. No search over
what a setup's settings hold and no search over its schema: both are
real questions, both would need a column nothing has built, and neither
has been asked yet.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.execution.aggregates.setup.state import SetupBeamline, SetupName

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many setups one page carries, by default and at most.

The same two numbers every other list in this context uses, and
deliberately not another pair. A caller paging one collection and then
another should not have to learn that the page sizes differ.
"""


@dataclass(frozen=True)
class ListSetups:
    """Read a page of setups, newest first.

    Any of the three filters narrows by equality and together they narrow
    to the intersection. All three is a setup's whole key, which holds one
    setup, or two where a race let a second definition through; a listing
    is where that second one shows.
    """

    beamline: SetupBeamline | None = None
    operation_id: UUID | None = None
    name: SetupName | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None

    @classmethod
    def from_filters(
        cls,
        *,
        beamline: str | None,
        operation_id: UUID | None = None,
        name: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> "ListSetups":
        """Build a query from the plain values a surface receives.

        The wrapping happens here rather than at each edge so both surfaces
        get one answer to what an unacceptable filter is: `SetupBeamline`
        trims and bounds its value and `SetupName` holds its to the
        alphabet a step carries, and either refuses with the error that
        refuses it at definition. A name no setup could hold is refused
        rather than quietly matching nothing.
        """
        return cls(
            beamline=SetupBeamline(beamline) if beamline is not None else None,
            operation_id=operation_id,
            name=SetupName(name) if name is not None else None,
            limit=limit,
            cursor=cursor,
        )


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListSetups"]
