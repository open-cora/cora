"""The entrypoint: building a provider from a name, and printing the answer."""

from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

import thinker.__main__ as main_module
from tests._fakes import RecordingKeeper, ScriptedInference, a_case, a_question
from thinker.__main__ import ALREADY_TAKEN, asked, concluding_for, main, reported
from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop
from thinker.config import ConfigError, ThinkerConfig
from thinker.think import Thought

if TYPE_CHECKING:
    from pathlib import Path

UNSTORABLE: list[Conclusion] = [
    Stop(said="met"),
    Abstain(said="nothing"),
    Refer(said="look"),
]

CONFIG = """
[keeper]
base_url = "https://keeper.example"
token = "a-token"

[inference]
profile = "tests.test_main:build_inference"
"""


def build_inference() -> ScriptedInference:
    """Named by the profile above, so the loader has something real to find."""
    return ScriptedInference()


NOT_CALLABLE = "a string, not a factory"


def _config(profile: str) -> ThinkerConfig:
    return ThinkerConfig(
        base_url="https://keeper.example", token="a-token", inference_profile=profile
    )


def test_concluding_for_builds_what_the_profile_names() -> None:
    built = concluding_for(_config("tests.test_main:build_inference"))
    assert isinstance(built, ScriptedInference)


def test_concluding_for_refuses_a_module_that_will_not_import() -> None:
    """At startup rather than at the moment of thinking, so nothing is half done."""
    with pytest.raises(ConfigError, match="will not import"):
        concluding_for(_config("nowhere.at.all:build"))


def test_concluding_for_refuses_a_name_the_module_does_not_have() -> None:
    with pytest.raises(ConfigError, match="nothing by that name"):
        concluding_for(_config("tests.test_main:absent"))


def test_concluding_for_refuses_a_name_that_is_not_callable() -> None:
    with pytest.raises(ConfigError, match="not callable"):
        concluding_for(_config("tests.test_main:NOT_CALLABLE"))


def test_reported_names_the_conclusion_by_its_own_word() -> None:
    """A caller branches on a word rather than on which fields are present."""
    thought = Thought(
        case=a_case(), conclusion=Abstain(said="nothing"), proposal_id=None, inquiry_id="inquiry-1"
    )
    assert reported(thought)["conclusion"] == "abstain"


@pytest.mark.parametrize(
    "conclusion",
    UNSTORABLE,
    ids=lambda c: type(c).__name__,
)
def test_reported_carries_what_a_conclusion_said_when_the_record_cannot(
    conclusion: Conclusion,
) -> None:
    """The only place three of the four conclusions exist at all."""
    thought = Thought(
        case=a_case(), conclusion=conclusion, proposal_id=None, inquiry_id="inquiry-1"
    )
    answer = reported(thought)
    assert answer["said"] == conclusion.said
    assert answer["proposal_id"] is None


def test_reported_carries_the_operation_and_parameters_only_for_a_proposal() -> None:
    proposed = Thought(
        case=a_case(),
        conclusion=Propose("op-9", {"exposure": 2}, said="go again"),
        proposal_id="proposal-1",
        inquiry_id="inquiry-1",
    )
    assert reported(proposed)["operation_id"] == "op-9"
    assert reported(proposed)["parameters"] == {"exposure": 2}

    abstained = Thought(
        case=a_case(), conclusion=Abstain(said="nothing"), proposal_id=None, inquiry_id="inquiry-1"
    )
    assert "operation_id" not in reported(abstained)


def test_reported_says_how_much_of_the_case_the_record_actually_covered() -> None:
    """A conclusion drawn from two of six steps supports very little."""
    thought = Thought(
        case=a_case(became=("Done", None, None)),
        conclusion=Abstain(said="nothing"),
        proposal_id=None,
        inquiry_id="inquiry-1",
    )
    answer = reported(thought)
    assert answer["ran_to_the_end"] is False
    assert answer["unreached"] == 2


def test_reported_is_json_a_caller_can_read() -> None:
    thought = Thought(
        case=a_case(objective="find the edge"),
        conclusion=Propose("op-9", {"exposure": 2}, said="go again"),
        proposal_id="proposal-1",
        inquiry_id="inquiry-1",
    )
    round_tripped = json.loads(json.dumps(reported(thought)))
    assert round_tripped["objective"] == "find the edge"
    assert round_tripped["proposal_id"] == "proposal-1"


def test_main_exits_two_on_a_configuration_that_will_not_load(tmp_path: Path) -> None:
    path = tmp_path / "thinker.toml"
    path.write_text("[keeper]\n", encoding="utf-8")
    assert (
        main(["--config", str(path), "--execution", "exec-1", "--objective", "find the edge"]) == 2
    )


def test_main_exits_two_on_a_profile_that_names_nothing(tmp_path: Path) -> None:
    """Refused before a single request is spent on reading an execution."""
    path = tmp_path / "thinker.toml"
    path.write_text(
        CONFIG.replace("tests.test_main:build_inference", "nowhere:build"), encoding="utf-8"
    )
    assert (
        main(["--config", str(path), "--execution", "exec-1", "--objective", "find the edge"]) == 2
    )


def test_main_requires_an_execution_to_think_about(tmp_path: Path) -> None:
    path = tmp_path / "thinker.toml"
    path.write_text(CONFIG, encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--config", str(path)])


def _arguments(**overrides: str | None) -> argparse.Namespace:
    """The namespace `_parse` would build, without going through argv."""
    fields: dict[str, str | None] = {"inquiry": None, "execution": None, "objective": None}
    fields.update(overrides)
    return argparse.Namespace(**fields)


def test_asked_opens_a_question_when_given_an_execution() -> None:
    """The mode somebody at a terminal uses. The asking is recorded, which
    is what makes the answer findable afterwards by anybody but them."""
    keeper = RecordingKeeper()

    question = asked(keeper, _arguments(execution="exec-7", objective="find the edge"))

    assert keeper.opened == [("exec-7", "find the edge")]
    assert question is not None
    assert (question.execution_id, question.objective) == ("exec-7", "find the edge")


def test_asked_does_not_claim_a_question_it_just_opened() -> None:
    """Nobody else can hold an id minted a moment ago, so the claim would
    record an event that says nothing."""
    keeper = RecordingKeeper()

    asked(keeper, _arguments(execution="exec-7", objective="find the edge"))

    assert keeper.claimed == []


def test_asked_claims_a_question_it_was_handed() -> None:
    """The id came from somewhere, so somewhere else may have it too."""
    keeper = RecordingKeeper()

    question = asked(keeper, _arguments(inquiry="inquiry-9"))

    assert keeper.claimed == ["inquiry-9"]
    assert question is not None
    assert question.inquiry_id == "inquiry-9"


def test_asked_reads_the_question_off_the_record_rather_than_the_command_line() -> None:
    """Both the execution and the objective come back from the inquiry,
    which is what lets a question put over another surface be answered."""
    keeper = RecordingKeeper(holds=a_question(execution_id="exec-4", objective="is it converged"))

    question = asked(keeper, _arguments(inquiry="inquiry-9"))

    assert question is not None
    assert (question.execution_id, question.objective) == ("exec-4", "is it converged")


def test_asked_gives_up_a_question_another_thinker_holds() -> None:
    """A refused claim is not a fault, so nothing raises and nothing is
    read: the caller stops before spending an inference on it."""
    keeper = RecordingKeeper(withholds=True)

    assert asked(keeper, _arguments(inquiry="inquiry-9")) is None
    assert keeper.reads == []


def test_main_exits_three_when_the_question_was_already_taken(tmp_path: Path) -> None:
    """Its own status, because nothing failed and nothing was concluded."""
    path = tmp_path / "thinker.toml"
    path.write_text(CONFIG)

    with patch.object(main_module, "HttpKeeper", return_value=RecordingKeeper(withholds=True)):
        status = main(["--config", str(path), "--inquiry", "inquiry-9"])

    assert status == ALREADY_TAKEN


def test_main_prints_the_answer_and_exits_zero_after_answering(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "thinker.toml"
    path.write_text(CONFIG)
    keeper = RecordingKeeper()

    with patch.object(main_module, "HttpKeeper", return_value=keeper):
        status = main(["--config", str(path), "--inquiry", "inquiry-9"])

    printed = json.loads(capsys.readouterr().out)
    assert status == 0
    assert printed["inquiry_id"] == "inquiry-9"
    assert len(keeper.answered) == 1


def test_parsing_refuses_naming_neither_an_inquiry_nor_an_execution() -> None:
    with pytest.raises(SystemExit):
        main(["--config", "unused.toml"])


def test_parsing_refuses_naming_both_an_inquiry_and_an_execution() -> None:
    """They are two ways to name one question, and both would leave the
    command with two."""
    with pytest.raises(SystemExit):
        main(["--config", "unused.toml", "--inquiry", "i-1", "--execution", "e-1"])


def test_parsing_refuses_an_execution_with_no_objective() -> None:
    """The record will not hold a question with nothing asked, so the
    refusal happens here rather than after a request."""
    with pytest.raises(SystemExit):
        main(["--config", "unused.toml", "--execution", "exec-1"])


def test_parsing_refuses_an_objective_beside_an_inquiry_that_carries_one() -> None:
    with pytest.raises(SystemExit):
        main(["--config", "unused.toml", "--inquiry", "i-1", "--objective", "find the edge"])
