"""Adapters this bounded context supplies to its own read port.

Two, and they are the two halves of one question. `RunSummaryLookup` is
declared with the Run aggregate, because a run summary is Execution's to
define; `PostgresRunSummaryLookup` reads the projection a deployment
maintains and `InMemoryRunSummaryLookup` folds the streams when there is
no database to project into.

Different from Authority's adapters package, which implements a port
declared in infrastructure. This port is declared and implemented in the
same context, because nothing outside Execution has any use for a run
summary.
"""

from aroc.execution.adapters.in_memory_run_summary_lookup import (
    InMemoryRunSummaryLookup,
)
from aroc.execution.adapters.postgres_run_summary_lookup import (
    PostgresRunSummaryLookup,
)

__all__ = ["InMemoryRunSummaryLookup", "PostgresRunSummaryLookup"]
