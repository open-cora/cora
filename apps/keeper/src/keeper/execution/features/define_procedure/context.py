"""The sibling state this slice's decision needs, loaded before deciding.

A decider is pure: it takes values and returns events, and it never reads
from a port. This slice has to check every run's parameters
against the schema its operation declares, and each operation is a different
stream.

So the handler does the reading and hands the result across as plain
data. `dispatch_execution/context.py` next door is the same shape for
one procedure; this one carries an operation per run, because a
procedure may run more than once.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from keeper.execution.aggregates.operation import Operation
from keeper.execution.aggregates.setup import Setup, SetupName


@dataclass(frozen=True)
class DefineProcedureContext:
    """The operations this procedure's runs cite, and the setups they name, as they stand now.

    Keyed by id and holding each distinct operation once, because a procedure
    that runs the same operation at five sample positions should not make
    this system read the same stream five times.

    Every run's operation is present. The handler refuses a procedure
    citing an operation that does not exist before building this, so the
    decider may look one up without handling a miss.

    Read at handler time, which means it can be stale by the time the
    append lands. That is accepted: the alternative is a transaction
    spanning several streams, and what this check is for is catching a
    caller who got the parameters wrong, or cited an operation retired
    long ago, not racing an operation being retired.

    `setups` holds each setup a run of a setup-taking operation names, at
    the procedure's beamline and its latest revision, keyed by operation
    and name; `keeper.execution.resolving` says how they are found. Unlike
    the operations, a miss here is expected and is the decider's to refuse:
    a run naming a setup nobody defined is a refusal about the run, with an
    index, rather than a missing record. No default, so a caller that never
    resolved any says so with an empty mapping, and every run that takes a
    setup is then refused rather than passed.
    """

    operations: Mapping[UUID, Operation]
    setups: Mapping[tuple[UUID, SetupName], Setup]


__all__ = ["DefineProcedureContext"]
