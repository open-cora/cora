"""Read, conclude, advise: the three moves and what each of them does not do."""

from __future__ import annotations

import pytest

from tests._fakes import (
    KeeperUnreachableError,
    ProviderUnreachableError,
    RecordingKeeper,
    ScriptedInference,
    a_reading,
)
from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop
from thinker.think import think

UNSTORABLE: list[Conclusion] = [
    Stop(said="met"),
    Abstain(said="nothing"),
    Refer(said="look at this"),
]


def test_think_asks_the_keeper_for_the_execution_it_was_given() -> None:
    keeper = RecordingKeeper()
    think("exec-7", keeper=keeper, inference=ScriptedInference())
    assert keeper.asked == ["exec-7"]


def test_think_puts_the_objective_on_the_case_without_asking_the_keeper_for_it() -> None:
    """Nothing in the record holds it, so it never has business crossing the seam.

    The keeper is asked for an execution and nothing else. An objective
    that travelled out to an adapter could only be handed straight back,
    and a seam taking one would invite an adapter to look it up.
    """
    keeper = RecordingKeeper()
    inference = ScriptedInference()
    think("exec-7", keeper=keeper, inference=inference, objective="find the edge")
    assert keeper.asked == ["exec-7"]
    assert inference.saw[0].objective == "find the edge"


def test_think_hands_the_inference_the_whole_case_and_not_the_outcomes() -> None:
    """The reason both halves are read at all.

    An inference given only what became of each step would be scoring
    verdicts with no subjects.
    """
    keeper = RecordingKeeper(answers=a_reading(became=("Done", None)))
    inference = ScriptedInference()
    think("exec-7", keeper=keeper, inference=inference)
    seen = inference.saw[0]
    assert [step.asked for step in seen.steps] == [{"kind": "move"}, {"kind": "move"}]
    assert [step.became for step in seen.steps] == ["Done", None]


def test_think_puts_a_proposed_run_forward_and_returns_its_id() -> None:
    keeper = RecordingKeeper(proposal_id="proposal-42")
    inference = ScriptedInference(answers=Propose("plan-3", {"exposure": 2}, said="go again"))
    thought = think("exec-7", keeper=keeper, inference=inference)
    assert keeper.proposed == [("plan-3", {"exposure": 2})]
    assert thought.proposal_id == "proposal-42"


@pytest.mark.parametrize("conclusion", UNSTORABLE, ids=lambda c: type(c).__name__)
def test_think_writes_nothing_for_a_conclusion_the_record_cannot_hold(
    conclusion: Conclusion,
) -> None:
    keeper = RecordingKeeper()
    think("exec-7", keeper=keeper, inference=ScriptedInference(answers=conclusion))
    assert keeper.proposed == []


@pytest.mark.parametrize("conclusion", UNSTORABLE, ids=lambda c: type(c).__name__)
def test_think_returns_a_conclusion_the_record_cannot_hold_to_its_caller(
    conclusion: Conclusion,
) -> None:
    """The three unstorable arms reach somebody, which is what makes them real."""
    thought = think(
        "exec-7", keeper=RecordingKeeper(), inference=ScriptedInference(answers=conclusion)
    )
    assert thought.conclusion is conclusion
    assert thought.proposal_id is None


def test_think_returns_the_case_it_read_alongside_what_it_concluded() -> None:
    """A conclusion is only as good as the case behind it, so both come back."""
    keeper = RecordingKeeper(answers=a_reading(became=("Done", None, None)))
    thought = think("exec-7", keeper=keeper, inference=ScriptedInference())
    assert thought.case.execution_id == "exec-1"
    assert len(thought.case.unreached()) == 2


def test_think_does_not_turn_a_provider_that_raised_into_an_abstention() -> None:
    """A thinker that could not look has not looked and found nothing."""
    with pytest.raises(ProviderUnreachableError):
        think("exec-7", keeper=RecordingKeeper(), inference=ScriptedInference(raises=True))


def test_think_does_not_swallow_a_keeper_that_would_not_take_the_proposal() -> None:
    inference = ScriptedInference(answers=Propose("plan-3", {}, said="go again"))
    with pytest.raises(KeeperUnreachableError):
        think("exec-7", keeper=RecordingKeeper(refuses=True), inference=inference)


def test_think_concludes_before_it_writes_anything() -> None:
    """A thinker that died mid-run has advised nothing.

    The provider raises, so the only way a proposal could have been made
    is if the write came first.
    """
    keeper = RecordingKeeper()
    with pytest.raises(ProviderUnreachableError):
        think("exec-7", keeper=keeper, inference=ScriptedInference(raises=True))
    assert keeper.proposed == []
