"""The decision that taking a proposal produces.

Three invariants, and two of them share an error class. The cases worth
separating are therefore about the diagnostic the error carries, because
that is the only thing telling a caller which of the two happened.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from aroc.counsel.aggregates.proposal import (
    Proposal,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
    ProposalTaken,
)
from aroc.counsel.features.take_proposal import (
    TakeProposal,
    TakeProposalContext,
    decide,
)
from aroc.execution.aggregates.run import Run, RunStatus
from aroc.shared.identifier import Identifier

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_PARAMETERS: dict[str, Any] = {"exposure_time_s": 0.1}
_REF = Identifier(scheme="bluesky-uid", value="0f2c9d1e-6b9a-4a5e-9a2f-1d3c5b7e9f11")


def _open_proposal(plan_id: object | None = None) -> Proposal:
    return Proposal(
        id=uuid4(),
        actor_id=uuid4(),
        plan_id=plan_id if plan_id is not None else uuid4(),  # pyright: ignore[reportArgumentType]
        parameters=dict(_PARAMETERS),
    )


def _run_of(plan_id: object) -> TakeProposalContext:
    return TakeProposalContext(
        run=Run(
            id=uuid4(),
            plan_id=plan_id,  # pyright: ignore[reportArgumentType]
            parameters=dict(_PARAMETERS),
            external_ref=_REF,
            status=RunStatus.COMPLETED,
        )
    )


def test_taking_an_open_proposal_emits_one_event() -> None:
    proposal = _open_proposal()
    run_id = uuid4()

    events = decide(
        proposal,
        TakeProposal(proposal_id=proposal.id, run_id=run_id),
        context=_run_of(proposal.plan_id),
        now=_NOW,
    )

    assert events == [ProposalTaken(proposal_id=proposal.id, run_id=run_id, occurred_at=_NOW)]


def test_taking_a_proposal_that_was_never_made_is_refused() -> None:
    with pytest.raises(ProposalNotFoundError):
        decide(
            None,
            TakeProposal(proposal_id=uuid4(), run_id=uuid4()),
            context=_run_of(uuid4()),
            now=_NOW,
        )


def test_taking_one_twice_is_refused_and_names_the_first_run() -> None:
    first_run = uuid4()
    proposal = _open_proposal()
    taken = Proposal(
        id=proposal.id,
        actor_id=proposal.actor_id,
        plan_id=proposal.plan_id,
        parameters=proposal.parameters,
        run_id=first_run,
    )

    with pytest.raises(ProposalCannotBeTakenError) as caught:
        decide(
            taken,
            TakeProposal(proposal_id=taken.id, run_id=uuid4()),
            context=_run_of(taken.plan_id),
            now=_NOW,
        )

    assert caught.value.taken_by == first_run


def test_a_run_of_a_different_plan_is_refused_and_names_both_plans() -> None:
    proposal = _open_proposal()
    other_plan = uuid4()

    with pytest.raises(ProposalCannotBeTakenError) as caught:
        decide(
            proposal,
            TakeProposal(proposal_id=proposal.id, run_id=uuid4()),
            context=_run_of(other_plan),
            now=_NOW,
        )

    assert caught.value.proposed_plan_id == proposal.plan_id
    assert caught.value.run_plan_id == other_plan
    assert caught.value.taken_by is None


def test_the_two_refusals_are_told_apart_by_the_run_on_the_error() -> None:
    """One class, two causes, and `taken_by` is what discriminates them."""
    proposal = _open_proposal()
    taken = Proposal(
        id=proposal.id,
        actor_id=proposal.actor_id,
        plan_id=proposal.plan_id,
        parameters=proposal.parameters,
        run_id=uuid4(),
    )

    with pytest.raises(ProposalCannotBeTakenError) as already:
        decide(
            taken,
            TakeProposal(proposal_id=taken.id, run_id=uuid4()),
            context=_run_of(taken.plan_id),
            now=_NOW,
        )
    with pytest.raises(ProposalCannotBeTakenError) as mismatch:
        decide(
            proposal,
            TakeProposal(proposal_id=proposal.id, run_id=uuid4()),
            context=_run_of(uuid4()),
            now=_NOW,
        )

    assert (already.value.taken_by is None, mismatch.value.taken_by is None) == (False, True)


def test_parameters_that_differ_from_what_was_proposed_do_not_refuse_the_take() -> None:
    """The plan is compared and the values are not, because engines normalize."""
    proposal = _open_proposal()
    context = TakeProposalContext(
        run=Run(
            id=uuid4(),
            plan_id=proposal.plan_id,
            parameters={"exposure_time_s": 0.1, "num_projections": 1500},
            external_ref=_REF,
            status=RunStatus.COMPLETED,
        )
    )

    events = decide(
        proposal,
        TakeProposal(proposal_id=proposal.id, run_id=uuid4()),
        context=context,
        now=_NOW,
    )

    assert len(events) == 1


def test_the_event_is_stamped_with_the_moment_the_decider_was_given() -> None:
    """Which moment that is belongs to the handler, not here.

    The decider stamps `now` and never reads the command's reported
    time, the way every run transition's does. Choosing between a
    reported time and the clock is the handler's, and the test next to
    that handler is where the choice is pinned.
    """
    proposal = _open_proposal()

    events = decide(
        proposal,
        TakeProposal(
            proposal_id=proposal.id,
            run_id=uuid4(),
            occurred_at=datetime(2026, 9, 18, 6, 0, tzinfo=UTC),
        ),
        context=_run_of(proposal.plan_id),
        now=_NOW,
    )

    assert events[0].occurred_at == _NOW
