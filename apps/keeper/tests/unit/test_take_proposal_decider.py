"""The decision that taking a proposal produces.

Five invariants, and four of them share an error class. The cases worth
separating are therefore about the diagnostic the error carries, because
that is the only thing telling a caller which of the four happened.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest

from keeper.counsel.aggregates.proposal import (
    Proposal,
    ProposalCannotBeTakenError,
    ProposalNotFoundError,
    ProposalTaken,
    ProposedRun,
)
from keeper.counsel.features.take_proposal import (
    TakeProposal,
    TakeProposalContext,
    decide,
)
from keeper.execution.aggregates.procedure import (
    ComposedStep,
    ProcedureStep,
    RunStep,
    SetStep,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 9, 19, 14, 30, tzinfo=UTC)
_PARAMETERS: dict[str, Any] = {"exposure_time_s": 0.1}


def _open_proposal(operation_id: UUID | None = None) -> Proposal:
    return Proposal(
        id=uuid4(),
        actor_id=uuid4(),
        runs=(
            ProposedRun(
                operation_id=operation_id if operation_id is not None else uuid4(),
                parameters=dict(_PARAMETERS),
            ),
        ),
    )


def _open_plan(*operation_ids: UUID) -> Proposal:
    return Proposal(
        id=uuid4(),
        actor_id=uuid4(),
        runs=tuple(ProposedRun(operation_id=each, parameters={}) for each in operation_ids),
    )


def _operation_of(proposal: Proposal) -> UUID:
    """The operation a proposal of one run proposes."""
    return proposal.runs[0].operation_id


def _taken(proposal: Proposal, *, by: UUID) -> Proposal:
    return Proposal(
        id=proposal.id,
        actor_id=proposal.actor_id,
        runs=proposal.runs,
        execution_id=uuid4(),
        step_id=by,
    )


def _acquisition_of(operation_id: UUID | None) -> TakeProposalContext:
    """The composed step behind the run, as the handler found it.

    An operation of None is the move case: the step exists and was composed to
    drive a motor rather than to ask an engine for anything.
    """
    step: ProcedureStep = (
        SetStep(record="2bmb:m1", to=0.0)
        if operation_id is None
        else RunStep(operation_id=operation_id, parameters={}, scopes=("2bmb:det:",))
    )
    return TakeProposalContext(composed=ComposedStep(id=uuid4(), step=step))


def _take(proposal_id: UUID, **overrides: object) -> TakeProposal:
    fields: dict[str, object] = {
        "proposal_id": proposal_id,
        "execution_id": uuid4(),
        "step_id": uuid4(),
    }
    fields.update(overrides)
    return TakeProposal(**fields)  # pyright: ignore[reportArgumentType]


def test_taking_an_open_proposal_emits_one_event() -> None:
    proposal = _open_proposal()
    execution_id = uuid4()
    step_id = uuid4()

    events = decide(
        proposal,
        _take(proposal.id, execution_id=execution_id, step_id=step_id),
        context=_acquisition_of(_operation_of(proposal)),
        now=_NOW,
    )

    assert events == [
        ProposalTaken(
            proposal_id=proposal.id,
            execution_id=execution_id,
            step_id=step_id,
            occurred_at=_NOW,
        )
    ]


def test_taking_a_proposal_that_was_never_made_is_refused() -> None:
    with pytest.raises(ProposalNotFoundError):
        decide(
            None,
            _take(uuid4()),
            context=_acquisition_of(uuid4()),
            now=_NOW,
        )


def test_taking_one_twice_is_refused_and_names_the_first_step() -> None:
    """The step and not the execution around it.

    An execution may hold a thousand steps, so naming it would tell a
    caller almost nothing about what already took the proposal.
    """
    first_step = uuid4()
    proposal = _taken(_open_proposal(), by=first_step)

    with pytest.raises(ProposalCannotBeTakenError) as caught:
        decide(
            proposal,
            _take(proposal.id),
            context=_acquisition_of(_operation_of(proposal)),
            now=_NOW,
        )

    assert caught.value.taken_by == first_step


def test_a_step_that_ran_a_different_operation_is_refused_and_names_both_operations() -> None:
    proposal = _open_proposal()
    other_operation = uuid4()

    with pytest.raises(ProposalCannotBeTakenError) as caught:
        decide(
            proposal,
            _take(proposal.id),
            context=_acquisition_of(other_operation),
            now=_NOW,
        )

    assert caught.value.proposed_operation_id == _operation_of(proposal)
    assert caught.value.step_operation_id == other_operation
    assert caught.value.taken_by is None


def test_a_set_cannot_take_a_proposal_and_is_not_reported_as_a_mismatch() -> None:
    """A move runs no operation, so the comparison below would refuse it too.

    What separates the two is the message. Told the step ran a different
    operation and given none to compare against, a caller goes looking for a
    closer run; told the step runs no operation at all, it knows the
    reference itself is wrong.
    """
    proposal = _open_proposal()

    with pytest.raises(ProposalCannotBeTakenError, match="runs no operation") as caught:
        decide(
            proposal,
            _take(proposal.id),
            context=_acquisition_of(None),
            now=_NOW,
        )

    assert caught.value.step_operation_id is None
    assert caught.value.proposed_operation_id is None


def test_the_four_refusals_are_told_apart_by_what_the_error_carries() -> None:
    """One class, four causes, and the attributes discriminate them."""
    proposal = _open_proposal()
    taken = _taken(proposal, by=uuid4())
    plan = _open_plan(uuid4(), uuid4())

    with pytest.raises(ProposalCannotBeTakenError) as already:
        decide(taken, _take(taken.id), context=_acquisition_of(_operation_of(taken)), now=_NOW)
    with pytest.raises(ProposalCannotBeTakenError) as several:
        decide(plan, _take(plan.id), context=_acquisition_of(_operation_of(plan)), now=_NOW)
    with pytest.raises(ProposalCannotBeTakenError) as mismatch:
        decide(proposal, _take(proposal.id), context=_acquisition_of(uuid4()), now=_NOW)
    with pytest.raises(ProposalCannotBeTakenError) as move:
        decide(proposal, _take(proposal.id), context=_acquisition_of(None), now=_NOW)

    assert [
        (
            error.value.taken_by is None,
            error.value.run_count is None,
            error.value.step_operation_id is None,
        )
        for error in (already, several, mismatch, move)
    ] == [(False, True, True), (True, False, True), (True, True, False), (True, True, True)]


def test_a_plan_of_several_runs_is_refused_even_when_the_step_ran_its_first_run() -> None:
    """One step running one run of a plan is not the plan being followed,
    whichever run it was, so the step is not even consulted."""
    first = uuid4()
    plan = _open_plan(first, uuid4(), uuid4())

    with pytest.raises(ProposalCannotBeTakenError, match="plan of 3 runs") as caught:
        decide(plan, _take(plan.id), context=_acquisition_of(first), now=_NOW)

    assert caught.value.run_count == 3


def test_a_plan_of_one_run_is_taken_like_any_proposal_of_one_run() -> None:
    operation = uuid4()
    plan = _open_plan(operation)

    events = decide(plan, _take(plan.id), context=_acquisition_of(operation), now=_NOW)

    assert len(events) == 1


def test_a_plan_already_adopted_hears_that_it_is_closed_rather_than_that_it_is_a_plan() -> None:
    adopted_at = uuid4()
    plan = _taken(_open_plan(uuid4(), uuid4()), by=adopted_at)

    with pytest.raises(ProposalCannotBeTakenError) as caught:
        decide(plan, _take(plan.id), context=_acquisition_of(uuid4()), now=_NOW)

    assert (caught.value.taken_by, caught.value.run_count) == (adopted_at, None)


def test_a_step_dispatched_with_other_parameters_still_takes_the_proposal() -> None:
    """The operation is compared and nothing else is.

    What a step was dispatched with is not on its record at all: an
    execution copies the sentence and the operation, and the procedure keeps
    the rest. So this is not a comparison this decider declines to make,
    it is one the record cannot support, and the operation is what it can.
    """
    proposal = _open_proposal()

    events = decide(
        proposal,
        _take(proposal.id),
        context=_acquisition_of(_operation_of(proposal)),
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
        _take(proposal.id, occurred_at=datetime(2026, 9, 18, 6, 0, tzinfo=UTC)),
        context=_acquisition_of(_operation_of(proposal)),
        now=_NOW,
    )

    assert events[0].occurred_at == _NOW
