"""What the loop does with what the keeper hands it, and what keeps it alive.

Every seam here is a double and nothing sleeps. The loop's own clock is a
parameter for that reason: a test asserting that a failure costs a backoff
should not be the thing that spends it.

A turn is one pass: ask, maybe claim, maybe think. `_turns` bounds the
loop the way a signal handler would, which is the only way a `serve` ever
returns.

The arm worth naming is the one that does not exist. Nothing here asserts
that a failure becomes a conclusion, because nothing may: the loop catches
a provider that raised and tries again, and what reaches the record is
still nothing at all. `test_a_provider_that_raised_records_no_conclusion`
is the check that this stays true when the retrying is what changed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests._fakes import ProviderUnreachableError, RecordingKeeper, ScriptedInference
from thinker.case import Question
from thinker.conclusions import Abstain, Conclusion, Propose, Stop
from thinker.intake import serve

if TYPE_CHECKING:
    from collections.abc import Callable

    from thinker.case import Case
    from thinker.seams import Concluding

INQUIRY = "an-inquiry"
EXECUTION = "an-execution"


def _turns(count: int) -> Callable[[], bool]:
    """A `keep_going` that allows exactly this many passes."""
    remaining = iter(range(count))
    return lambda: next(remaining, None) is not None


class _FailsOnceInference:
    """Raises the first time it is asked and answers every time after.

    Local rather than a flag on `ScriptedInference`, because the shared
    double is about what a provider was handed and this is about a loop
    surviving one bad turn. One test wants it.
    """

    def __init__(self, answers: Conclusion) -> None:
        self._answers = answers
        self.asked = 0

    def conclude(self, case: Case) -> Conclusion:
        _ = case
        self.asked += 1
        if self.asked == 1:
            raise ProviderUnreachableError("the provider could not be reached")
        return self._answers


def _question(inquiry_id: str = INQUIRY) -> Question:
    return Question(
        inquiry_id=inquiry_id,
        execution_id=EXECUTION,
        objective="is one scan enough",
    )


def _serve(
    keeper: RecordingKeeper,
    *,
    turns: int = 1,
    inference: Concluding | None = None,
    slept: list[float] | None = None,
    said: list[str] | None = None,
) -> Concluding:
    thinking = inference if inference is not None else ScriptedInference(Stop(said="enough"))
    serve(
        keeper,
        claiming=keeper,
        observing=keeper,
        advising=keeper,
        concluding=thinking,
        wait=7.0,
        backoff=3.0,
        keep_going=_turns(turns),
        pause=(slept if slept is not None else []).append,
        note=(said if said is not None else []).append,
    )
    return thinking


def test_a_quiet_keeper_asks_again_and_claims_nothing() -> None:
    keeper = RecordingKeeper()

    _serve(keeper, turns=3)

    assert keeper.taken == [7.0, 7.0, 7.0], "it asked once per turn, with the wait it was given"
    assert keeper.claimed == []
    assert keeper.answered == []


def test_a_question_that_is_there_is_claimed_and_answered() -> None:
    keeper = RecordingKeeper(waiting=[_question()])

    _serve(keeper)

    assert keeper.claimed == [INQUIRY]
    assert [answer[0] for answer in keeper.answered] == [INQUIRY]


def test_the_question_taken_is_the_one_read_and_the_one_answered() -> None:
    """Two questions in and two answers out, each against its own id.

    A loop that carried the first question into the second turn would
    pass every check that looks at one turn, and would answer one
    inquiry twice while leaving the other claimed and open.
    """
    keeper = RecordingKeeper(waiting=[_question("first"), _question("second")])

    _serve(keeper, turns=2)

    assert keeper.claimed == ["first", "second"]
    assert [answer[0] for answer in keeper.answered] == ["first", "second"]


def test_a_question_another_thinker_holds_is_not_thought_about() -> None:
    """A refused claim is an ordinary race, so the turn ends and the
    next one asks again rather than the process stopping."""
    keeper = RecordingKeeper(waiting=[_question()], withholds=True)

    _serve(keeper, turns=2)

    assert keeper.claimed == [INQUIRY]
    assert keeper.reads == [], "it did not read an execution it had not won"
    assert keeper.answered == []
    assert keeper.taken == [7.0, 7.0], "it went back for another question"


def test_a_lost_claim_costs_no_backoff() -> None:
    """Losing a race is not a failure, and paying a backoff for one
    would idle a thinker every time two of them are running."""
    keeper = RecordingKeeper(waiting=[_question()], withholds=True)
    slept: list[float] = []

    _serve(keeper, slept=slept)

    assert slept == []


def test_a_keeper_that_raised_is_waited_out_and_asked_again() -> None:
    """Two questions and a keeper that will not take a proposal, so both
    turns fail and neither failure is the last thing the loop does."""
    keeper = RecordingKeeper(waiting=[_question("first"), _question("second")], refuses=True)
    slept: list[float] = []

    proposing = ScriptedInference(Propose("op-3", {}, said="go again"))
    _serve(keeper, inference=proposing, turns=2, slept=slept)

    assert slept == [3.0, 3.0], "each failed turn cost one backoff"
    assert keeper.taken == [7.0, 7.0], "it kept asking"


def test_a_provider_that_raised_records_no_conclusion() -> None:
    """The rule the loop must not quietly reverse.

    Catching broadly is what keeps a daemon alive, and it would be a
    short step from there to writing `Abstain` so the question does not
    sit open. That would report a thinker that looked and found nothing,
    when it is a thinker that did not look.
    """
    keeper = RecordingKeeper(waiting=[_question()])

    _serve(keeper, inference=ScriptedInference(Abstain(said="nothing"), raises=True))

    assert keeper.claimed == [INQUIRY], "it took the question up"
    assert keeper.answered == [], "and left it unanswered rather than inventing one"
    assert keeper.proposed == []


def test_a_failing_turn_does_not_end_the_loop() -> None:
    """The whole reason the catch is broad: the question after a bad one
    is still answered, without anything having restarted the process."""
    keeper = RecordingKeeper(waiting=[_question("bad"), _question("good")])
    inference = _FailsOnceInference(Stop(said="enough"))

    _serve(keeper, inference=inference, turns=2)

    assert [answer[0] for answer in keeper.answered] == ["good"]


def test_what_it_says_names_the_question_and_the_conclusion() -> None:
    """A daemon's log is the only account of a turn that a person sees,
    so it carries both ids and the word that came back."""
    keeper = RecordingKeeper(waiting=[_question()])
    said: list[str] = []

    _serve(keeper, said=said)

    assert any(INQUIRY in line and EXECUTION in line for line in said)
    assert any(line.endswith("stop") for line in said)


def test_being_told_to_stop_ends_the_loop_and_says_so() -> None:
    keeper = RecordingKeeper()
    said: list[str] = []

    _serve(keeper, turns=0, said=said)

    assert keeper.taken == []
    assert said == ["asking for questions to answer", "stopped asking for questions to answer"]
