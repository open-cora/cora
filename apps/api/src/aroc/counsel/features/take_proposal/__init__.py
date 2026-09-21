"""The take_proposal slice, re-exported so callers read `.bind`."""

from aroc.counsel.features.take_proposal.command import TakeProposal
from aroc.counsel.features.take_proposal.context import TakeProposalContext
from aroc.counsel.features.take_proposal.decider import decide
from aroc.counsel.features.take_proposal.handler import Handler, bind
from aroc.counsel.features.take_proposal.route import router

__all__ = [
    "Handler",
    "TakeProposal",
    "TakeProposalContext",
    "bind",
    "decide",
    "router",
]
