"""Execution's read-side projections.

`PROJECTION_NAME` is deliberately not re-exported. Each projection module
defines one and they are different strings, so a package-level name would
have to pick a winner and every importer would be one rename away from
querying the wrong table. Import it from the module whose table you mean.
"""

from aroc.execution.projections.plan_summary import PlanSummaryProjection
from aroc.execution.projections.run_summary import (
    STATUS_BY_EVENT_TYPE,
    RunSummaryProjection,
)

__all__ = ["STATUS_BY_EVENT_TYPE", "PlanSummaryProjection", "RunSummaryProjection"]
