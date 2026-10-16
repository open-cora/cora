"""The question: which executions, newest first, and where do I carry on from?

The query a fold cannot answer. `GetExecution` names the execution it wants; this
one is asking which execution to name, and the only way to answer that from
an event log is to have kept a summary of it as the events arrived.

Three kinds of parameter. The filter says which executions. The limit
says how many of them. The cursor says where the last page stopped.

No classmethod wrapping the filter, unlike the operation and procedure lists.
A procedure id is a UUID and both surfaces parse it before a query
exists, so there is nothing left for the domain to refuse.
"""

from dataclasses import dataclass
from uuid import UUID

from keeper.execution.aggregates.execution import ExecutionBeamline, ExecutionStatus

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100
"""How many executions one page carries, by default and at most.

A default rather than everything, because a beamline running for a year
has more executions than any caller meant to ask for. A maximum rather than
trusting the number sent, because the cost of a page is paid by the
server.
"""


@dataclass(frozen=True)
class ListExecutions:
    """Read a page of executions, newest first.

    `procedure_id` narrows to the executions dispatched for that procedure,
    which is the question this slice exists for: a routine composed once
    is walked every time it runs, so "how did this procedure go" means
    reading its executions.

    Not guaranteed to match at most one execution, and not meant to be. The
    interesting page is usually several: the same procedure run at
    different times, some ended and some not.

    `beamline`, `status` and `runs` are the work intake's three. A
    conductor asks for all of them: its own beamline, `Dispatched`, and
    what its engine can run. They are separate fields rather than one
    because each answers on its own: an operator asks what 7-BM is
    doing, or what is still dispatched anywhere.

    `runs` is what the caller can run, and a row matches when every
    routine it needs is in that set. Until it existed a conductor
    claimed whatever came back and found out afterwards, which costs an
    execution each time, because a claim is a write with nothing to
    undo it.

    **`None` is not the empty set.** `None` means do not narrow, which is
    what a person browsing wants. The empty set means a caller that runs
    nothing, which is a conductor with no engine, and it is offered only
    the executions that run nothing either. Collapsing the two would
    hand every run-bearing execution to the one deployment that can
    drive none of them.

    All four narrow together. None is required, and a query with none of
    them is every execution, newest first.
    """

    procedure_id: UUID | None = None
    beamline: ExecutionBeamline | None = None
    status: ExecutionStatus | None = None
    runs: frozenset[str] | None = None
    limit: int = DEFAULT_PAGE_SIZE
    cursor: str | None = None


__all__ = ["DEFAULT_PAGE_SIZE", "MAX_PAGE_SIZE", "ListExecutions"]
