"""Read, conclude, record: the three moves and what each of them does not do."""

from __future__ import annotations

import pytest

from tests._fakes import (
    KeeperUnreachableError,
    ProviderUnreachableError,
    RecordingKeeper,
    ScriptedInference,
    a_question,
    a_reading,
)
from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop
from thinker.think import think

UNPROPOSED: list[Conclusion] = [
    Stop(said="met"),
    Abstain(said="nothing"),
    Refer(said="look at this"),
]
"""The three conclusions that put no run forward.

They were once the three the record could not hold at all, which is the
distinction this landing removed: all four are written now, and what
separates these is only that none of them proposes anything.
"""


def test_think_reads_the_execution_the_question_names() -> None:
    keeper = RecordingKeeper()
    think(a_question(execution_id="exec-7"), keeper=keeper, inference=ScriptedInference())
    assert keeper.reads == ["exec-7"]


def test_think_puts_the_questions_objective_on_the_case() -> None:
    """The objective now arrives from the record rather than from argv.

    It crosses the seam because an inquiry holds one, which is what makes
    a conclusion readable later by somebody who was not there to be told
    what was being pursued.
    """
    inference = ScriptedInference()
    think(a_question(objective="find the edge"), keeper=RecordingKeeper(), inference=inference)
    assert inference.saw[0].objective == "find the edge"


def test_think_hands_the_inference_the_whole_case_and_not_the_outcomes() -> None:
    """The reason both halves are read at all.

    An inference given only what became of each step would be scoring
    verdicts with no subjects.
    """
    keeper = RecordingKeeper(answers=a_reading(became=("Done", None)))
    inference = ScriptedInference()
    think(a_question(), keeper=keeper, inference=inference)
    seen = inference.saw[0]
    assert [step.asked for step in seen.steps] == [{"kind": "move"}, {"kind": "move"}]
    assert [step.became for step in seen.steps] == ["Done", None]


def test_think_puts_a_proposed_run_forward_and_returns_its_id() -> None:
    keeper = RecordingKeeper(proposal_id="proposal-42")
    inference = ScriptedInference(answers=Propose("plan-3", {"exposure": 2}, said="go again"))
    thought = think(a_question(), keeper=keeper, inference=inference)
    assert keeper.proposed == [("plan-3", {"exposure": 2})]
    assert thought.proposal_id == "proposal-42"


@pytest.mark.parametrize("conclusion", UNPROPOSED, ids=lambda c: type(c).__name__)
def test_think_proposes_nothing_for_a_conclusion_that_puts_no_run_forward(
    conclusion: Conclusion,
) -> None:
    keeper = RecordingKeeper()
    think(a_question(), keeper=keeper, inference=ScriptedInference(answers=conclusion))
    assert keeper.proposed == []


@pytest.mark.parametrize("conclusion", UNPROPOSED, ids=lambda c: type(c).__name__)
def test_think_writes_every_conclusion_onto_the_inquiry_that_asked(
    conclusion: Conclusion,
) -> None:
    """The gap this closed. Before the inquiry these three reached no
    record at all, so a thinker that looked and found nothing left the
    same trace as one that never ran."""
    keeper = RecordingKeeper()
    think(
        a_question(inquiry_id="inquiry-9"),
        keeper=keeper,
        inference=ScriptedInference(answers=conclusion),
    )
    (inquiry_id, written, _boundary, proposal_id) = keeper.answered[0]
    assert (inquiry_id, written, proposal_id) == ("inquiry-9", conclusion, None)


def test_think_names_the_proposal_it_wrote_on_the_answer() -> None:
    """The join, and the only arm that carries one."""
    keeper = RecordingKeeper(proposal_id="proposal-42")
    inference = ScriptedInference(answers=Propose("plan-3", {}, said="go again"))
    think(a_question(), keeper=keeper, inference=inference)
    assert keeper.answered[0][3] == "proposal-42"


def test_think_writes_the_proposal_before_the_answer_that_cites_it() -> None:
    """A thinker that dies between the two leaves a proposal that reads as
    any other actor's, which is the harmless direction. The reverse leaves
    an inquiry naming a proposal nobody made."""
    keeper = RecordingKeeper(refuses=True)
    inference = ScriptedInference(answers=Propose("plan-3", {}, said="go again"))
    with pytest.raises(KeeperUnreachableError):
        think(a_question(), keeper=keeper, inference=inference)
    assert keeper.answered == []


def test_think_reports_how_much_of_the_execution_it_saw() -> None:
    """The observation boundary, counted from the case the inference was
    shown rather than from anything else, so the two cannot describe
    different readings."""
    keeper = RecordingKeeper(answers=a_reading(became=("Done", None, None), ended=False))
    think(a_question(), keeper=keeper, inference=ScriptedInference())
    boundary = keeper.answered[0][2]
    assert (boundary.observed_step_count, boundary.execution_ended) == (1, False)


def test_think_reports_a_closed_execution_it_saw_every_step_of() -> None:
    keeper = RecordingKeeper(answers=a_reading(became=("Done", "Done"), ended=True))
    think(a_question(), keeper=keeper, inference=ScriptedInference())
    boundary = keeper.answered[0][2]
    assert (boundary.observed_step_count, boundary.execution_ended) == (2, True)


def test_think_returns_the_case_it_read_alongside_what_it_concluded() -> None:
    """A conclusion is only as good as the case behind it, so both come back."""
    keeper = RecordingKeeper(answers=a_reading(became=("Done", None, None)))
    thought = think(a_question(), keeper=keeper, inference=ScriptedInference())
    assert thought.case.execution_id == "exec-1"
    assert len(thought.case.unreached()) == 2


def test_think_returns_the_inquiry_it_answered() -> None:
    thought = think(
        a_question(inquiry_id="inquiry-9"),
        keeper=RecordingKeeper(),
        inference=ScriptedInference(),
    )
    assert thought.inquiry_id == "inquiry-9"


def test_think_does_not_turn_a_provider_that_raised_into_an_abstention() -> None:
    """A thinker that could not look has not looked and found nothing."""
    with pytest.raises(ProviderUnreachableError):
        think(a_question(), keeper=RecordingKeeper(), inference=ScriptedInference(raises=True))


def test_think_does_not_swallow_a_keeper_that_would_not_take_the_proposal() -> None:
    inference = ScriptedInference(answers=Propose("plan-3", {}, said="go again"))
    with pytest.raises(KeeperUnreachableError):
        think(a_question(), keeper=RecordingKeeper(refuses=True), inference=inference)


def test_think_concludes_before_it_writes_anything() -> None:
    """A thinker that died mid-run has advised nothing and answered nothing.

    The provider raises, so the only way either write could have happened
    is if it came first.
    """
    keeper = RecordingKeeper()
    with pytest.raises(ProviderUnreachableError):
        think(a_question(), keeper=keeper, inference=ScriptedInference(raises=True))
    assert keeper.proposed == []
    assert keeper.answered == []
