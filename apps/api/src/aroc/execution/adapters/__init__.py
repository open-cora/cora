"""Adapters this bounded context supplies to its own read port.

Six, in three pairs, and each pair is the two halves of one question.
The ports are declared with the aggregates they summarise, because a
plan, a run and a walk summary are all Execution's to define. The Postgres half
of each reads the projection a deployment maintains; the in-memory half
folds the streams when there is no database to project into.

Different from Authority's adapters package, which implements a port
declared in infrastructure. This port is declared and implemented in the
same context, because nothing outside Execution has any use for a run
summary.
"""

from aroc.execution.adapters.in_memory_plan_summary_lookup import (
    InMemoryPlanSummaryLookup,
)
from aroc.execution.adapters.in_memory_run_summary_lookup import (
    InMemoryRunSummaryLookup,
)
from aroc.execution.adapters.in_memory_walk_summary_lookup import (
    InMemoryWalkSummaryLookup,
)
from aroc.execution.adapters.postgres_plan_summary_lookup import (
    PostgresPlanSummaryLookup,
)
from aroc.execution.adapters.postgres_run_summary_lookup import (
    PostgresRunSummaryLookup,
)
from aroc.execution.adapters.postgres_walk_summary_lookup import (
    PostgresWalkSummaryLookup,
)

__all__ = [
    "InMemoryPlanSummaryLookup",
    "InMemoryRunSummaryLookup",
    "InMemoryWalkSummaryLookup",
    "PostgresPlanSummaryLookup",
    "PostgresRunSummaryLookup",
    "PostgresWalkSummaryLookup",
]
