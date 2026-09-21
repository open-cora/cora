"""Read models this bounded context maintains, and the call that registers them."""

from aroc.counsel.projections.proposal_summary import (
    PROJECTION_NAME,
    ProposalSummaryProjection,
)
from aroc.counsel.projections.register import register_counsel_projections

__all__ = [
    "PROJECTION_NAME",
    "ProposalSummaryProjection",
    "register_counsel_projections",
]
