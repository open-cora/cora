"""The sibling state this slice's decision needs, loaded before deciding.

The first context module in this tree, so it is worth saying what the
shape is for. A decider is pure: it takes values and returns events, and
it never reads from a port. This slice still has to check the parameters
against the schema the plan declares, and the plan is a different stream.

So the handler does the reading and hands the result across as plain
data. The decider receives a loaded plan and treats it as a value it was
given, which is what keeps it testable without a store and replayable
without one.

One field today, and a dataclass rather than a bare `Plan` parameter. The
next thing a run's genesis has to check will be loaded the same way and
will join this holder, and a named type means that arrives as a field
rather than as a second positional argument threaded through three
signatures.
"""

from dataclasses import dataclass

from aroc.execution.aggregates.plan import Plan


@dataclass(frozen=True)
class ReportRunContext:
    """The plan this run says it ran, as it stands right now.

    Read at handler time, which means it can be stale by the time the
    append lands. That is accepted: the alternative is a transaction
    spanning two streams, and what this check is for is catching a caller
    who got the parameters wrong, not racing a plan being edited.
    """

    plan: Plan


__all__ = ["ReportRunContext"]
