"""Seams and a transport that keep what they were asked, so thinking can be checked.

None of them talks to anything. What a real provider does with a case is
the provider's business and is behind a seam precisely so that nothing here
has to run one, and the keeper's own behaviour is checked in the keeper.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from thinker.case import Boundary, Case, Outcome, Question, Reading, Step
from thinker.conclusions import Abstain

if TYPE_CHECKING:
    from thinker.conclusions import Conclusion

Proposed = tuple[str, Mapping[str, object]]
"""One proposal a keeper seam received: the operation, and the values for it.

A runtime alias rather than an annotation, because the recorder below
builds a list from it and a name only the type checker can see would not
be there when it ran.
"""

Answered = tuple[str, "Conclusion", Boundary, str | None]
"""One answer a keeper seam received: which inquiry, and all of what it was told.

The boundary is in it rather than checked separately, because what a test
of the writing half most needs to state is that the conclusion and the
amount seen arrived together. They are one event on the record and a fake
that kept them apart would let a caller send one without the other.
"""


def an_ending(value: Outcome | str | None) -> Outcome | None:
    """One step's outcome, from a bare word or from the whole thing.

    A bare word is what most of this suite wants, because the pairing, the
    counting and the writing all read whether an outcome is there and never
    which word it is. A test that cares what the engine said passes an
    `Outcome` and says so in the one place it matters, rather than every
    builder in the file growing two more arguments for it.
    """
    if isinstance(value, str):
        return Outcome(reported=value, engine_state=None, cause=None)
    return value


def a_question(
    *,
    inquiry_id: str = "inquiry-1",
    execution_id: str = "exec-1",
    objective: str = "find the edge",
) -> Question:
    """A question naming the execution `a_reading` describes."""
    return Question(inquiry_id=inquiry_id, execution_id=execution_id, objective=objective)


def a_case(
    *,
    execution_id: str = "exec-1",
    procedure: str = "a scan",
    became: tuple[Outcome | str | None, ...] = ("Done", "Done"),
    ended: bool = True,
    objective: str | None = None,
) -> Case:
    """A case with one step per entry in `became`, numbered from zero."""
    return Case(
        execution_id=execution_id,
        procedure=procedure,
        steps=tuple(
            Step(
                index=index,
                step_id=f"step-{index}",
                asked={"kind": "set"},
                became=an_ending(outcome),
            )
            for index, outcome in enumerate(became)
        ),
        ended=ended,
        objective=objective,
    )


def a_reading(
    *,
    execution_id: str = "exec-1",
    procedure: str = "a scan",
    became: tuple[Outcome | str | None, ...] = ("Done", "Done"),
    ended: bool = True,
) -> Reading:
    """The unpaired halves that `a_case` is the assembly of.

    Keyed rather than ordered, the way the record keys them, so a test
    going through here exercises the real join instead of a case that was
    handed over already paired.

    A step with no outcome is left out of `became` entirely, which is what
    a walk that never reached it looks like. An adapter also has to handle
    the other shape, a step present in the record with a null outcome, and
    that one is covered where adapters are.
    """
    step_ids = tuple(f"step-{index}" for index in range(len(became)))
    return Reading(
        execution_id=execution_id,
        procedure=procedure,
        asked=tuple((step_id, {"kind": "set"}) for step_id in step_ids),
        became={
            step_id: an_ending(outcome)
            for step_id, outcome in zip(step_ids, became, strict=True)
            if outcome is not None
        },
        ended=ended,
    )


class KeeperUnreachableError(RuntimeError):
    """The keeper seam was asked something and could not answer."""


@dataclass(slots=True)
class RecordingKeeper:
    """Answers with a reading it was given, and keeps every write it took.

    `refuses` turns the proposing half into a failure without touching
    anything else, which is the arrangement a test of what reaches the
    keeper after a conclusion needs.

    `withholds` makes a claim come back False, which is the ordinary
    refusal rather than a fault: another thinker has the question. It is a
    separate flag from `refuses` because they are opposite kinds of thing
    and a test that conflated them would be checking that a race looks
    like an outage.

    `reads` is what `read` was asked for, and is named for the verb rather
    than for the question, because `ask` is now a verb of its own here.

    `waiting` is answered in order and then exhausted, so a loop given
    two questions and left running finds nothing on every turn after the
    second. That is what lets a test bound the loop by what it hands over
    rather than by how many turns it lets it take.
    """

    answers: Reading = field(default_factory=a_reading)
    holds: Question = field(default_factory=a_question)
    proposed: list[Proposed] = field(default_factory=list[Proposed])
    answered: list[Answered] = field(default_factory=list[Answered])
    opened: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    claimed: list[str] = field(default_factory=list[str])
    reads: list[str] = field(default_factory=list[str])
    waiting: list[Question] = field(default_factory=list[Question])
    taken: list[float] = field(default_factory=list[float])
    looked: list[str] = field(default_factory=list[str])
    """Every lookup a profile made, in order, as `<verb> <argument>`.

    One list for the five verbs rather than one each, because what a test
    of the looking seam asks is whether a profile went back to the record
    at all and for what, and that reads better as a sequence than as five
    counters.
    """
    refuses: bool = False
    withholds: bool = False
    proposal_id: str = "proposal-1"

    def take(self, wait: float) -> Question | None:
        self.taken.append(wait)
        return self.waiting.pop(0) if self.waiting else None

    def read(self, execution_id: str) -> Reading:
        self.reads.append(execution_id)
        return self.answers

    def ask(self, execution_id: str, objective: str) -> Question:
        self.opened.append((execution_id, objective))
        return Question(
            inquiry_id=self.holds.inquiry_id,
            execution_id=execution_id,
            objective=objective,
        )

    def read_back(self, inquiry_id: str) -> Question:
        return Question(
            inquiry_id=inquiry_id,
            execution_id=self.holds.execution_id,
            objective=self.holds.objective,
        )

    def claim(self, inquiry_id: str) -> bool:
        self.claimed.append(inquiry_id)
        return not self.withholds

    def answer(
        self,
        inquiry_id: str,
        conclusion: Conclusion,
        boundary: Boundary,
        proposal_id: str | None,
    ) -> None:
        self.answered.append((inquiry_id, conclusion, boundary, proposal_id))

    def propose(self, operation_id: str, parameters: Mapping[str, object]) -> str:
        if self.refuses:
            raise KeeperUnreachableError("the keeper would not take the proposal")
        self.proposed.append((operation_id, parameters))
        return self.proposal_id

    def execution(self, execution_id: str) -> dict[str, object]:
        self.looked.append(f"execution {execution_id}")
        return {"execution_id": execution_id, "beamline": "2-bm", "steps": []}

    def procedure(self, procedure_id: str) -> dict[str, object]:
        self.looked.append(f"procedure {procedure_id}")
        return {"procedure_id": procedure_id, "steps": []}

    def operation_schema(self, operation_id: str) -> dict[str, object]:
        self.looked.append(f"operation_schema {operation_id}")
        return {}

    def prior_runs(self, beamline: str, limit: int) -> list[dict[str, object]]:
        self.looked.append(f"prior_runs {beamline}")
        _ = limit
        return []

    def datasets_for(self, step_id: str) -> list[dict[str, object]]:
        self.looked.append(f"datasets_for {step_id}")
        return []


class ProviderUnreachableError(RuntimeError):
    """The inference seam was asked for a conclusion and raised instead."""


@dataclass(slots=True)
class ScriptedInference:
    """Returns a conclusion decided in advance, and keeps the case it saw.

    The case is kept because the thing most worth checking about this seam
    is what it was handed: an inference given only the record would be
    scoring outcomes with no subjects, and only the argument shows that.
    """

    answers: Conclusion = field(default_factory=lambda: Abstain(said="nothing to go on"))
    saw: list[Case] = field(default_factory=list[Case])
    raises: bool = False

    def conclude(self, case: Case) -> Conclusion:
        self.saw.append(case)
        if self.raises:
            raise ProviderUnreachableError("the provider could not be reached")
        return self.answers


@dataclass(frozen=True, slots=True)
class CannedResponse:
    """One HTTP answer, in the shape the adapter's `Response` reads."""

    status_code: int
    payload: Any = None
    text: str = ""

    def json(self) -> Any:
        return self.payload


@dataclass(slots=True)
class CannedHttp:
    """Answers each path from a table, and keeps every request made.

    Keyed by path rather than by call order, so a test states what the
    keeper holds instead of what sequence the adapter happens to ask in.
    An unmapped path answers 404, which is what the keeper would say about
    a thing it does not have.
    """

    gets: Mapping[str, CannedResponse] = field(default_factory=dict[str, CannedResponse])
    posts: Mapping[str, CannedResponse] = field(default_factory=dict[str, CannedResponse])
    requested: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])
    sent: list[tuple[str, Mapping[str, Any] | None]] = field(
        default_factory=list[tuple[str, Mapping[str, Any] | None]]
    )
    headers_seen: list[Mapping[str, str]] = field(default_factory=list[Mapping[str, str]])
    asked_with: list[tuple[str, Mapping[str, str] | None, float | None]] = field(
        default_factory=list[tuple[str, Mapping[str, str] | None, float | None]]
    )

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CannedResponse:
        path = self._path(url)
        self.requested.append(("GET", path))
        self.headers_seen.append(headers or {})
        self.asked_with.append((path, params, timeout))
        return self.gets.get(path, CannedResponse(404, text="no such thing"))

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> CannedResponse:
        path = self._path(url)
        self.requested.append(("POST", path))
        self.sent.append((path, json))
        self.headers_seen.append(headers or {})
        return self.posts.get(path, CannedResponse(404, text="no such route"))

    @staticmethod
    def _path(url: str) -> str:
        """The path the adapter asked for, with the base URL taken off.

        By finding the first single slash after the scheme rather than by
        stripping a base this fake was told, so a test does not have to
        repeat the base URL it already passed to the adapter.
        """
        after_scheme = url.split("://", 1)[-1]
        slash = after_scheme.find("/")
        return after_scheme[slash:] if slash >= 0 else "/"
