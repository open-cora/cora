"""The four-valued output vocabulary, and the properties the rest of the package assumes."""

from __future__ import annotations

import dataclasses
import typing

import pytest

from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop

ARMS = typing.get_args(Conclusion)


def test_the_conclusion_union_has_an_arm_for_each_of_the_four_answers() -> None:
    """Guard the enumeration: the checks below range over whatever this finds."""
    assert set(ARMS) == {Propose, Stop, Abstain, Refer}


@pytest.mark.parametrize("arm", ARMS, ids=lambda arm: arm.__name__)
def test_every_conclusion_carries_what_it_said(arm: type) -> None:
    """`__main__` reads `said` off whichever arm came back, without asking which."""
    assert "said" in {field.name for field in dataclasses.fields(arm)}


@pytest.mark.parametrize("arm", ARMS, ids=lambda arm: arm.__name__)
def test_a_conclusion_cannot_be_edited_after_it_is_reached(arm: type) -> None:
    conclusion = arm(said="because") if arm is not Propose else Propose("p", {}, said="because")
    with pytest.raises(dataclasses.FrozenInstanceError):
        conclusion.said = "something else"  # pyright: ignore[reportAttributeAccessIssue]


@pytest.mark.parametrize("arm", ARMS, ids=lambda arm: arm.__name__)
def test_no_conclusion_carries_a_score_it_gave_itself(arm: type) -> None:
    """The refusal the module is written around, kept as a check rather than a note.

    A confidence added later would be a thinker rating its own conclusion,
    which reads as measurement and is assertion.
    """
    named = {field.name for field in dataclasses.fields(arm)}
    assert not named & {"confidence", "score", "certainty", "quality", "rating"}


def test_stop_and_abstain_are_different_types_rather_than_one_with_a_flag() -> None:
    """The pair it costs most to collapse.

    A facility told the objective is met when the thinker merely saw
    nothing stops early; one told the reverse keeps running. Two classes
    make the mix-up a type error instead of a wrong string.
    """
    assert Stop is not Abstain
    assert Stop(said="met") != Abstain(said="met")


def test_only_a_proposal_carries_something_the_keeper_can_store() -> None:
    named = {arm.__name__: {f.name for f in dataclasses.fields(arm)} for arm in ARMS}
    assert named["Propose"] == {"plan_id", "parameters", "said"}
    assert named["Stop"] == named["Abstain"] == named["Refer"] == {"said"}
