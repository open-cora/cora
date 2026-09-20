"""Read models this bounded context maintains, and the call that registers them."""

from aroc.custody.projections.dataset_summary import (
    PROJECTION_NAME,
    DatasetSummaryProjection,
)
from aroc.custody.projections.register import register_custody_projections

__all__ = [
    "PROJECTION_NAME",
    "DatasetSummaryProjection",
    "register_custody_projections",
]
