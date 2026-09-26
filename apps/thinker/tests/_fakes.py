"""Seams and a transport that keep what they were asked, so thinking can be checked.

None of them talks to anything. What a real provider does with a case is
the provider's business and is behind a seam precisely so that nothing here
has to run one, and the keeper's own behaviour is checked in the keeper.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from thinker.case import Case, Reading, Step
from thinker.conclusions import Abstain

if TYPE_CHECKING:
    from thinker.conclusions import Conclusion

Proposed = tuple[str, Mapping[str, object]]
"""One proposal a keeper seam received: the plan, and the values for it.

A runtime alias rather than an annotation, because the recorder below
builds a list from it and a name only the type checker can see would not
be there when it ran.
"""


def a_case(
    *,
    execution_id: str = "exec-1",
    procedure: str = "a scan",
    became: tuple[str | None, ...] = ("Done", "Done"),
    ended: bool = True,
    objective: str | None = None,
) -> Case:
    """A case with one step per entry in `became`, numbered from zero."""
    return Case(
        execution_id=execution_id,
        procedure=procedure,
        steps=tuple(
            Step(index=index, step_id=f"step-{index}", asked={"kind": "move"}, became=outcome)
            for index, outcome in enumerate(became)
        ),
        ended=ended,
        objective=objective,
    )


def a_reading(
    *,
    execution_id: str = "exec-1",
    procedure: str = "a scan",
    became: tuple[str | None, ...] = ("Done", "Done"),
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
        asked=tuple((step_id, {"kind": "move"}) for step_id in step_ids),
        became={
            step_id: outcome
            for step_id, outcome in zip(step_ids, became, strict=True)
            if outcome is not None
        },
        ended=ended,
    )


class KeeperUnreachableError(RuntimeError):
    """The keeper seam was asked something and could not answer."""


@dataclass(slots=True)
class RecordingKeeper:
    """Answers with a reading it was given, and keeps every proposal made.

    `refuses` turns the writing half into a failure without touching the
    reading half, which is the arrangement a test of what reaches the
    keeper after a conclusion needs.
    """

    answers: Reading = field(default_factory=a_reading)
    proposed: list[Proposed] = field(default_factory=list[Proposed])
    asked: list[str] = field(default_factory=list[str])
    refuses: bool = False
    proposal_id: str = "proposal-1"

    def read(self, execution_id: str) -> Reading:
        self.asked.append(execution_id)
        return self.answers

    def propose(self, plan_id: str, parameters: Mapping[str, object]) -> str:
        if self.refuses:
            raise KeeperUnreachableError("the keeper would not take the proposal")
        self.proposed.append((plan_id, parameters))
        return self.proposal_id


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

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> CannedResponse:
        path = self._path(url)
        self.requested.append(("GET", path))
        self.headers_seen.append(headers or {})
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
