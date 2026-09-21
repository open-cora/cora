"""The Proposal aggregate: state, events, evolver, and its two read paths."""

from aroc.counsel.aggregates.proposal.events import (
    ProposalEvent,
    ProposalMade,
    ProposalTaken,
    from_stored,
    to_payload,
)
from aroc.counsel.aggregates.proposal.evolver import evolve, fold
from aroc.counsel.aggregates.proposal.read import (
    PROPOSAL_STREAM_TYPE,
    load_proposal,
    load_proposal_with_version,
)
from aroc.counsel.aggregates.proposal.state import (
    InvalidProposalParametersError,
    Proposal,
    ProposalAlreadyExistsError,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
)

__all__ = [
    "PROPOSAL_STREAM_TYPE",
    "InvalidProposalParametersError",
    "Proposal",
    "ProposalAlreadyExistsError",
    "ProposalCannotBeTakenError",
    "ProposalEvent",
    "ProposalMade",
    "ProposalNotFoundError",
    "ProposalTaken",
    "evolve",
    "fold",
    "from_stored",
    "load_proposal",
    "load_proposal_with_version",
    "to_payload",
]
