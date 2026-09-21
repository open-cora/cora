"""The decision: what taking a proposal produces.

Update-style, so the state comes in already folded and `new_id` is
absent: this command names its stream rather than creating one.

Pure. No awaits, no ports, no clock.
"""

from datetime import datetime

from aroc.counsel.aggregates.proposal import (
    Proposal,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
    ProposalTaken,
)
from aroc.counsel.features.take_proposal.command import TakeProposal
from aroc.counsel.features.take_proposal.context import TakeProposalContext


def decide(
    state: Proposal | None,
    command: TakeProposal,
    *,
    context: TakeProposalContext,
    now: datetime,
) -> list[ProposalTaken]:
    """Decide the events produced by taking a proposal.

    Invariants:
      - State must not be None, or no such proposal was made
        -> ProposalNotFoundError
      - The proposal must not already have a run against it
        -> ProposalCannotBeTakenError
      - The run must have run the plan the proposal names
        -> ProposalCannotBeTakenError

    **Taking one twice is refused, and that is a domain claim rather
    than a safety rail.** A rerun after a failure is a new proposal,
    because the second run was chosen after seeing the first one fail,
    and that is a second choice. Refusing is also the reversible
    direction: allowing it later costs a sentence, and disallowing it
    later costs a migration.

    **The plan is compared and the parameters are not.** The agent that
    closes this loop resolves a run by an external reference, and
    Execution does not enforce that a reference is unique across
    streams, so a retried reporter makes two records of one engine run
    and the lookup returns both. Comparing the plan is the cheap guard
    against citing the wrong one. Comparing parameters would not be: an
    engine normalizes values and fills defaults, so a run's parameters
    can differ from what was proposed while still being the run that was
    proposed, and a dict comparison would refuse legitimate joins to
    catch a case nobody has seen.

    Both refusals share a class and a status, because the caller's next
    move is the same in kind: stop, and work out which run it meant. The
    error carries what tells them apart.
    """
    if state is None:
        raise ProposalNotFoundError(command.proposal_id)
    if state.run_id is not None:
        raise ProposalCannotBeTakenError.already_taken(state.id, state.run_id)
    if context.run.plan_id != state.plan_id:
        raise ProposalCannotBeTakenError.plan_mismatch(
            state.id,
            proposed_plan_id=state.plan_id,
            run_plan_id=context.run.plan_id,
        )
    return [
        ProposalTaken(
            proposal_id=command.proposal_id,
            run_id=command.run_id,
            occurred_at=now,
        )
    ]


__all__ = ["decide"]
