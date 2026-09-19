"""Execution's read-side projections, and the call that subscribes them.

`register_execution_projections` is re-exported from here, so a caller
writes the package rather than the module it happens to live in. The
context root re-exports it again, which is where the composition root
reads it from.

`PROJECTION_NAME` is deliberately not re-exported. Each projection module
defines one and they are different strings, so a package-level name would
have to pick a winner and every importer would be one rename away from
querying the wrong table. Import it from the module whose table you mean.
"""

from aroc.execution.projections.plan_summary import PlanSummaryProjection
from aroc.execution.projections.register import register_execution_projections
from aroc.execution.projections.run_summary import (
    STATUS_BY_EVENT_TYPE,
    RunSummaryProjection,
)

__all__ = [
    "STATUS_BY_EVENT_TYPE",
    "PlanSummaryProjection",
    "RunSummaryProjection",
    "register_execution_projections",
]
