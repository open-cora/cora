"""The question: which procedures, newest first, and where do I carry on from?

`GetProcedure` names the procedure it wants. This one is asking which
procedure to name, which a fold cannot answer: it would mean replaying
every procedure stream to see which ones match.

Two optional filters, a name and a beamline, and that is the whole of
it. No search over which operations a procedure runs and no search over
which devices it touches: both are real questions, both would need a
column nothing has built, and neither has been asked yet.

The beamline is here because the projection already carries the column
and the question is the one an operator has. Asking what a station can
run meant reading every procedure in the facility and filtering on the
far side, which works until the page size is reached and then quietly
stops working: a caller sees fifty procedures, keeps the handful at its
beamline, and never learns there was a second page.
"""

from dataclasses import dataclass

from keeper.execution.aggregates.procedure.state import ProcedureBeamline, ProcedureName

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many procedures one page carries, by default and at most.

The same two numbers the operation and run lists use, and deliberately not a
third pair. A caller paging one collection and then another should not
have to learn that the page sizes differ.
"""


@dataclass(frozen=True)
class ListProcedures:
    """Read a page of procedures, newest first.

    `name` may match more than one. Two procedures may share a name, so
    this returns however many there are rather than promising the one a
    caller hoped for, and choosing between them is the caller's to do.
    """

    name: ProcedureName | None = None
    beamline: ProcedureBeamline | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None

    @classmethod
    def from_filters(
        cls,
        *,
        name: str | None,
        beamline: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        cursor: str | None = None,
    ) -> "ListProcedures":
        """Build a query from the plain strings a surface receives.

        The wrapping happens here rather than at each edge so both
        surfaces get one answer to what an unacceptable filter is:
        `ProcedureName` and `ProcedureBeamline` trim and bound their
        value, and an over-long one is refused with the same error that
        refuses it at definition.

        Named for the filters rather than for the name, unlike the
        operation list's `with_name` next door. That one narrows by one
        thing and this one narrows by two, and a constructor still
        called `with_name` while taking a beamline would be the kind of
        small lie that survives for years.
        """
        return cls(
            name=ProcedureName(name) if name is not None else None,
            beamline=ProcedureBeamline(beamline) if beamline is not None else None,
            limit=limit,
            cursor=cursor,
        )


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListProcedures"]
