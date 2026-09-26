"""The entrypoint: building a provider from a name, and printing the answer."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tests._fakes import ScriptedInference, a_case
from thinker.__main__ import inference_for, main, reported
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


def test_inference_for_builds_what_the_profile_names() -> None:
    built = inference_for(_config("tests.test_main:build_inference"))
    assert isinstance(built, ScriptedInference)


def test_inference_for_refuses_a_module_that_will_not_import() -> None:
    """At startup rather than at the moment of thinking, so nothing is half done."""
    with pytest.raises(ConfigError, match="will not import"):
        inference_for(_config("nowhere.at.all:build"))


def test_inference_for_refuses_a_name_the_module_does_not_have() -> None:
    with pytest.raises(ConfigError, match="nothing by that name"):
        inference_for(_config("tests.test_main:absent"))


def test_inference_for_refuses_a_name_that_is_not_callable() -> None:
    with pytest.raises(ConfigError, match="not callable"):
        inference_for(_config("tests.test_main:NOT_CALLABLE"))


def test_reported_names_the_conclusion_by_its_own_word() -> None:
    """A caller branches on a word rather than on which fields are present."""
    thought = Thought(case=a_case(), conclusion=Abstain(said="nothing"), proposal_id=None)
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
    thought = Thought(case=a_case(), conclusion=conclusion, proposal_id=None)
    answer = reported(thought)
    assert answer["said"] == conclusion.said
    assert answer["proposal_id"] is None


def test_reported_carries_the_plan_and_parameters_only_for_a_proposal() -> None:
    proposed = Thought(
        case=a_case(),
        conclusion=Propose("plan-9", {"exposure": 2}, said="go again"),
        proposal_id="proposal-1",
    )
    assert reported(proposed)["plan_id"] == "plan-9"
    assert reported(proposed)["parameters"] == {"exposure": 2}

    abstained = Thought(case=a_case(), conclusion=Abstain(said="nothing"), proposal_id=None)
    assert "plan_id" not in reported(abstained)


def test_reported_says_how_much_of_the_case_the_record_actually_covered() -> None:
    """A conclusion drawn from two of six steps supports very little."""
    thought = Thought(
        case=a_case(became=("Done", None, None)),
        conclusion=Abstain(said="nothing"),
        proposal_id=None,
    )
    answer = reported(thought)
    assert answer["ran_to_the_end"] is False
    assert answer["unreached"] == 2


def test_reported_is_json_a_caller_can_read() -> None:
    thought = Thought(
        case=a_case(objective="find the edge"),
        conclusion=Propose("plan-9", {"exposure": 2}, said="go again"),
        proposal_id="proposal-1",
    )
    round_tripped = json.loads(json.dumps(reported(thought)))
    assert round_tripped["objective"] == "find the edge"
    assert round_tripped["proposal_id"] == "proposal-1"


def test_main_exits_two_on_a_configuration_that_will_not_load(tmp_path: Path) -> None:
    path = tmp_path / "thinker.toml"
    path.write_text("[keeper]\n", encoding="utf-8")
    assert main(["--config", str(path), "--execution", "exec-1"]) == 2


def test_main_exits_two_on_a_profile_that_names_nothing(tmp_path: Path) -> None:
    """Refused before a single request is spent on reading an execution."""
    path = tmp_path / "thinker.toml"
    path.write_text(
        CONFIG.replace("tests.test_main:build_inference", "nowhere:build"), encoding="utf-8"
    )
    assert main(["--config", str(path), "--execution", "exec-1"]) == 2


def test_main_requires_an_execution_to_think_about(tmp_path: Path) -> None:
    path = tmp_path / "thinker.toml"
    path.write_text(CONFIG, encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--config", str(path)])
