"""The sibling state this slice's decision needs, loaded before deciding.

A decider is pure: it takes values and returns events, and it never reads
from a port. This slice checks every run's values against the schema its
operation declares, and each operation is a stream in another bounded
context.

So the handler does the reading and hands the result across as plain
data. `MakeProposalContext` is the same shape for one run; this one
carries an operation per distinct operation the plan cites, the way
`DefineProcedureContext` does for a procedure's runs.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from keeper.execution.aggregates.operation import Operation


@dataclass(frozen=True)
class ProposePlanContext:
    """The operations the plan's runs cite, as they stand right now.

    Keyed by id and holding each distinct operation once, so a plan that
    moves data twice reads the transfer's stream once.

    Every run's operation is present. The handler refuses a plan citing an
    operation that does not exist before building this, so the decider may
    look one up without handling a miss.

    Read at handler time, which means it can be stale by the time the
    append lands. That is accepted for the reason `MakeProposalContext`
    gives: what this check is for is catching values that could not have
    run, not racing an operation being retired.
    """

    operations: Mapping[UUID, Operation]


__all__ = ["ProposePlanContext"]
