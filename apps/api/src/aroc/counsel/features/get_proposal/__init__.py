"""The get_proposal slice, re-exported so callers read `get_proposal.bind`."""

from aroc.counsel.features.get_proposal.handler import Handler, bind
from aroc.counsel.features.get_proposal.query import GetProposal
from aroc.counsel.features.get_proposal.route import router

__all__ = [
    "GetProposal",
    "Handler",
    "bind",
    "router",
]
