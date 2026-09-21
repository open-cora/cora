"""The make_proposal slice, re-exported so callers read `.bind`."""

from aroc.counsel.features.make_proposal.command import MakeProposal
from aroc.counsel.features.make_proposal.context import MakeProposalContext
from aroc.counsel.features.make_proposal.decider import decide
from aroc.counsel.features.make_proposal.handler import (
    Handler,
    IdempotentHandler,
    bind,
)
from aroc.counsel.features.make_proposal.route import router

__all__ = [
    "Handler",
    "IdempotentHandler",
    "MakeProposal",
    "MakeProposalContext",
    "bind",
    "decide",
    "router",
]
