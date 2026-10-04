"""The entrypoint: building a provider from a name, and printing the answer."""

from __future__ import annotations

import argparse
import json
import os
import signal
from contextlib import nullcontext
from typing import TYPE_CHECKING, cast
from unittest.mock import patch

import pytest

import thinker.__main__ as main_module
from tests._fakes import RecordingKeeper, ScriptedInference, a_case, a_question
from thinker import intake
from thinker.__main__ import ALREADY_TAKEN, asked, concluding_for, main, reported
from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop
from thinker.config import ConfigError, ThinkerConfig
from thinker.intake import DEFAULT_WAIT_SECONDS
from thinker.think import Thought

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from thinker.seams import Concluding

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


def build_inference(looking: object) -> ScriptedInference:
    """Named by the profile above, so the loader has something real to find.

    Takes the looking seam and ignores it, which is what a profile that
    decides from the case alone does.
    """
    _ = looking
    return ScriptedInference()


NOT_CALLABLE = "a string, not a factory"


def _config(profile: str) -> ThinkerConfig:
    return ThinkerConfig(
        base_url="https://keeper.example", token="a-token", inference_profile=profile
    )


def test_concluding_for_builds_what_the_profile_names() -> None:
    built = concluding_for(_config("tests.test_main:build_inference"), looking=RecordingKeeper())
    assert isinstance(built, ScriptedInference)


def test_concluding_for_refuses_a_module_that_will_not_import() -> None:
    """At startup rather than at the moment of thinking, so nothing is half done."""
    with pytest.raises(ConfigError, match="will not import"):
        concluding_for(_config("nowhere.at.all:build"), looking=RecordingKeeper())


def test_concluding_for_refuses_a_name_the_module_does_not_have() -> None:
    with pytest.raises(ConfigError, match="nothing by that name"):
        concluding_for(_config("tests.test_main:absent"), looking=RecordingKeeper())


def test_concluding_for_refuses_a_name_that_is_not_callable() -> None:
    with pytest.raises(ConfigError, match="not callable"):
        concluding_for(_config("tests.test_main:NOT_CALLABLE"), looking=RecordingKeeper())


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


def test_main_requires_a_mode_of_some_kind(tmp_path: Path) -> None:
    path = tmp_path / "thinker.toml"
    path.write_text(CONFIG, encoding="utf-8")
    with pytest.raises(SystemExit):
        main(["--config", str(path)])


def _serves_until_quiet(keeper: RecordingKeeper) -> Callable[..., None]:
    """The real loop, bounded by the questions the double is holding.

    `main` takes a `keep_going` and the entrypoint supplies one from the
    signal handler, so this overrides it with a turn count. The test
    spends no time and the loop under it is the real one.
    """
    turns = len(keeper.waiting)
    remaining = iter(range(turns))

    def serving(*args: object, **kwargs: object) -> None:
        real = cast("Callable[..., None]", intake.serve)
        kwargs["keep_going"] = lambda: next(remaining, None) is not None
        kwargs["pause"] = _nothing
        kwargs["note"] = _nothing
        real(*args, **kwargs)

    return serving


def _nothing(_value: object) -> None:
    return None


def _ignores_everything(*_args: object, **_kwargs: object) -> None:
    """A `serve` that returns at once, for a test about what was built."""
    return None


def _records_timeout(seen: list[float]) -> Callable[..., object]:
    """An `httpx.Client` stand-in that keeps the timeout it was built with."""

    def building(*_args: object, timeout: float = 0.0, **_kwargs: object) -> object:
        seen.append(timeout)
        return nullcontext(None)

    return building


def _arguments(**overrides: object) -> argparse.Namespace:
    """The namespace `_parse` would build, without going through argv."""
    fields: dict[str, object] = {
        "inquiry": None,
        "execution": None,
        "objective": None,
        "serve": False,
        "wait": DEFAULT_WAIT_SECONDS,
    }
    fields.update(overrides)
    return argparse.Namespace(**fields)


def test_asked_opens_a_question_when_given_an_execution() -> None:
    """The mode somebody at a terminal uses. The asking is recorded, which
    is what makes the answer findable afterwards by anybody but them."""
    keeper = RecordingKeeper()

    question = asked(
        keeper, claiming=keeper, arguments=_arguments(execution="exec-7", objective="find the edge")
    )

    assert keeper.opened == [("exec-7", "find the edge")]
    assert question is not None
    assert (question.execution_id, question.objective) == ("exec-7", "find the edge")


def test_asked_does_not_claim_a_question_it_just_opened() -> None:
    """Nobody else can hold an id minted a moment ago, so the claim would
    record an event that says nothing."""
    keeper = RecordingKeeper()

    asked(
        keeper, claiming=keeper, arguments=_arguments(execution="exec-7", objective="find the edge")
    )

    assert keeper.claimed == []


def test_asked_claims_a_question_it_was_handed() -> None:
    """The id came from somewhere, so somewhere else may have it too."""
    keeper = RecordingKeeper()

    question = asked(keeper, claiming=keeper, arguments=_arguments(inquiry="inquiry-9"))

    assert keeper.claimed == ["inquiry-9"]
    assert question is not None
    assert question.inquiry_id == "inquiry-9"


def test_asked_reads_the_question_off_the_record_rather_than_the_command_line() -> None:
    """Both the execution and the objective come back from the inquiry,
    which is what lets a question put over another surface be answered."""
    keeper = RecordingKeeper(holds=a_question(execution_id="exec-4", objective="is it converged"))

    question = asked(keeper, claiming=keeper, arguments=_arguments(inquiry="inquiry-9"))

    assert question is not None
    assert (question.execution_id, question.objective) == ("exec-4", "is it converged")


def test_asked_gives_up_a_question_another_thinker_holds() -> None:
    """A refused claim is not a fault, so nothing raises and nothing is
    read: the caller stops before spending an inference on it."""
    keeper = RecordingKeeper(withholds=True)

    assert asked(keeper, claiming=keeper, arguments=_arguments(inquiry="inquiry-9")) is None
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


def test_serving_answers_every_question_the_keeper_holds(tmp_path: Path) -> None:
    """The third mode, end to end through the entrypoint.

    Bounded by what the keeper has rather than by the default predicate,
    which never stops: `main` is called without one here, so the double
    standing in for `serve` supplies the turn count a signal handler
    would otherwise supply.
    """
    path = tmp_path / "thinker.toml"
    path.write_text(CONFIG)
    keeper = RecordingKeeper(waiting=[a_question(), a_question()])

    with (
        patch.object(main_module, "HttpKeeper", return_value=keeper),
        patch.object(main_module, "serve", _serves_until_quiet(keeper)),
    ):
        status = main(["--config", str(path), "--serve"])

    assert status == 0
    assert len(keeper.answered) == 2


def test_serving_holds_the_socket_open_longer_than_the_wait(tmp_path: Path) -> None:
    """The bug this shape exists to avoid.

    A client timeout equal to the wait races the keeper, so every ask
    that nothing answers raises rather than coming back empty. The
    process stays alive and stops picking questions up, which is the
    quietest way for this to be broken.
    """
    path = tmp_path / "thinker.toml"
    path.write_text(CONFIG)
    seen: list[float] = []

    with (
        patch.object(main_module, "HttpKeeper", return_value=RecordingKeeper()),
        patch.object(main_module, "serve", _ignores_everything),
        patch.object(main_module.httpx, "Client", _records_timeout(seen)),
    ):
        main(["--config", str(path), "--serve", "--wait", "30"])

    assert seen and seen[0] > 30.0, "the client outlived the wait it was going to ask for"


def test_parsing_refuses_serving_and_naming_a_question_at_once() -> None:
    """Two answers to which question, and no reason to prefer either."""
    with pytest.raises(SystemExit):
        main(["--config", "x.toml", "--serve", "--inquiry", "inquiry-9"])


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


def test_a_stop_signal_lets_the_thinking_in_progress_finish_and_be_written() -> None:
    """The orderly stop the loop's predicate exists for.

    The handler used to raise instead. A `KeyboardInterrupt` is a
    `BaseException`, so the loop's arm did not catch one: a signal
    landing inside a thinking unwound through it, and because nothing
    is written until there is a conclusion, the inquiry was left
    claimed with nothing on it. Driven by a real signal, because a
    double raising where one would land is what that failure was made
    of.

    The predicate is capped as well as signalled, so a handler that
    stops nothing fails this on its assertions rather than hanging the
    suite.
    """
    keeper = RecordingKeeper(waiting=[a_question(), a_question()])

    class StopsUsMidThinking:
        def conclude(self, case: object) -> Abstain:
            _ = case
            os.kill(os.getpid(), signal.SIGTERM)
            return Abstain(said="nothing to do")

    asked_to_stop = main_module.stop_on_termination()
    turns = iter(range(2))

    def keep_going() -> bool:
        return asked_to_stop() and next(turns, None) is not None

    before = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        intake.serve(
            keeper,
            claiming=keeper,
            observing=keeper,
            advising=keeper,
            concluding=cast("Concluding", StopsUsMidThinking()),
            keep_going=keep_going,
            pause=lambda _seconds: None,
            note=lambda _message: None,
        )
    finally:
        for number, handler in before.items():
            signal.signal(number, handler)

    assert len(keeper.answered) == 1, "the thinking in flight was written down"
    _inquiry_id, conclusion, _boundary, _proposal_id = keeper.answered[0]
    assert isinstance(conclusion, Abstain)
