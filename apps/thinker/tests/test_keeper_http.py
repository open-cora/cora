"""The keeper seam over HTTP: what it asks for, and what it makes of the answers."""

from __future__ import annotations

from typing import Any, get_args

import pytest

from tests._fakes import CannedHttp, CannedResponse
from thinker.adapters.keeper_http import (
    CONCLUSIONS,
    HttpKeeper,
    RequestRefusedError,
    UnknownConclusionError,
)
from thinker.case import Boundary
from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop

BASE = "https://keeper.example"

PROCEDURE: dict[str, Any] = {
    "procedure_id": "proc-1",
    "name": "an edge scan",
    "beamline": "2-BM",
    "steps": [
        {"kind": "move", "step_id": "s1", "record": "motor:x", "to": 1.5},
        {
            "kind": "run",
            "step_id": "s2",
            "operation_id": "op-9",
            "parameters": {"exposure": 2},
            "scopes": ["motor:x"],
        },
    ],
}

EXECUTION: dict[str, Any] = {
    "execution_id": "exec-1",
    "procedure_id": "proc-1",
    "procedure_name": "an edge scan",
    "beamline": "2-BM",
    "status": "Ended",
    "steps": [
        {
            "step_id": "es1",
            "describes": "move motor:x to 1.5",
            "procedure_step_id": "s1",
            "outcome": "Done",
            "engine_reference": None,
            "engine_state": None,
            "cause": None,
        },
        {
            "step_id": "es2",
            "describes": "run op-9",
            "procedure_step_id": "s2",
            "outcome": None,
            "engine_reference": None,
            "engine_state": None,
            "cause": None,
        },
    ],
}


def _keeper(
    *,
    execution: dict[str, Any] | None = None,
    procedure: dict[str, Any] | None = None,
    posts: dict[str, CannedResponse] | None = None,
) -> tuple[HttpKeeper, CannedHttp]:
    http = CannedHttp(
        gets={
            "/executions/exec-1": CannedResponse(200, execution if execution else EXECUTION),
            "/procedures/proc-1": CannedResponse(200, procedure if procedure else PROCEDURE),
        },
        posts=posts or {"/proposals": CannedResponse(201, {"proposal_id": "proposal-1"})},
    )
    return HttpKeeper(http=http, base_url=BASE, token="a-token"), http


def test_read_asks_for_the_execution_and_then_the_procedure_it_cites() -> None:
    """Two requests, because the keeper keeps the two halves apart."""
    keeper, http = _keeper()
    keeper.read("exec-1")
    assert http.requested == [("GET", "/executions/exec-1"), ("GET", "/procedures/proc-1")]


def test_read_keys_each_outcome_by_the_composed_step_it_cites() -> None:
    """The whole adapter contract, in one assertion.

    A walked step carries two ids: its own, and the composed step it was
    dispatched from. Only the second is what the intent is keyed by, and
    keying by the first would hand the core two halves that share no key
    and look like two executions.
    """
    keeper, _ = _keeper()
    reading = keeper.read("exec-1")
    assert reading.became == {"s1": "Done", "s2": None}
    assert [step_id for step_id, _ in reading.asked] == ["s1", "s2"]


def test_read_keys_the_record_the_same_way_whatever_order_it_arrives_in() -> None:
    """Nothing here depends on the two lists lining up, which is the point."""
    reversed_record = {**EXECUTION, "steps": list(reversed(EXECUTION["steps"]))}
    keeper, _ = _keeper(execution=reversed_record)
    assert keeper.read("exec-1").became == {"s1": "Done", "s2": None}


def test_read_carries_the_procedures_own_description_of_a_step() -> None:
    """Not interpreted into a shape of this package's own, so nothing is dropped."""
    keeper, _ = _keeper()
    assert keeper.read("exec-1").asked[1][1] == PROCEDURE["steps"][1]


def test_read_keeps_a_skipped_step_distinct_from_a_step_that_reported_nothing() -> None:
    """The keeper draws that line, so flattening it here would erase it."""
    skipped = {
        **EXECUTION,
        "steps": [{**EXECUTION["steps"][0]}, {**EXECUTION["steps"][1], "outcome": "Skipped"}],
    }
    keeper, _ = _keeper(execution=skipped)
    assert keeper.read("exec-1").became == {"s1": "Done", "s2": "Skipped"}


def test_read_takes_ended_off_the_status_rather_than_off_the_outcomes() -> None:
    keeper, _ = _keeper()
    assert keeper.read("exec-1").ended

    running = {**EXECUTION, "status": "Running"}
    keeper, _ = _keeper(execution=running)
    assert not keeper.read("exec-1").ended


def test_read_names_the_procedure_by_the_name_the_procedure_gives() -> None:
    """The execution carries a name too, and the two could drift apart."""
    keeper, _ = _keeper()
    assert keeper.read("exec-1").procedure == "an edge scan"


def test_read_sends_the_token_on_every_request() -> None:
    keeper, http = _keeper()
    keeper.read("exec-1")
    assert http.headers_seen == [{"Authorization": "Bearer a-token"}] * 2


def test_read_refuses_an_execution_the_keeper_does_not_hold() -> None:
    keeper = HttpKeeper(http=CannedHttp(), base_url=BASE, token="a-token")
    with pytest.raises(RequestRefusedError) as refused:
        keeper.read("exec-1")
    assert refused.value.status == 404
    assert refused.value.path == "/executions/exec-1"


def test_read_does_not_ask_for_a_procedure_when_the_execution_was_refused() -> None:
    http = CannedHttp()
    with pytest.raises(RequestRefusedError):
        HttpKeeper(http=http, base_url=BASE, token="a-token").read("exec-1")
    assert http.requested == [("GET", "/executions/exec-1")]


def test_propose_sends_the_operation_and_its_parameters() -> None:
    keeper, http = _keeper()
    keeper.propose("op-9", {"exposure": 2})
    assert http.sent == [("/proposals", {"operation_id": "op-9", "parameters": {"exposure": 2}})]


def test_propose_returns_the_id_the_keeper_gave_the_proposal() -> None:
    keeper, _ = _keeper(posts={"/proposals": CannedResponse(201, {"proposal_id": "proposal-42"})})
    assert keeper.propose("op-9", {}) == "proposal-42"


def test_propose_lets_a_refusal_of_the_operations_schema_through() -> None:
    """A proposal that could not have run is worth more as an error than a row."""
    keeper, _ = _keeper(posts={"/proposals": CannedResponse(400, text="exposure must be a number")})
    with pytest.raises(RequestRefusedError) as refused:
        keeper.propose("op-9", {"exposure": "two"})
    assert refused.value.status == 400
    assert "exposure must be a number" in str(refused.value)


def test_propose_refuses_an_answer_that_is_not_the_created_status() -> None:
    """200 on a route that creates something means the keeper is not the keeper."""
    keeper, _ = _keeper(posts={"/proposals": CannedResponse(200, {"proposal_id": "p"})})
    with pytest.raises(RequestRefusedError):
        keeper.propose("op-9", {})


def test_a_refusal_names_the_method_and_path_that_drew_it() -> None:
    keeper, _ = _keeper(posts={"/proposals": CannedResponse(403, text="not granted")})
    with pytest.raises(RequestRefusedError) as refused:
        keeper.propose("op-9", {})
    assert refused.value.method == "POST"
    assert refused.value.path == "/proposals"
    assert "POST /proposals: 403" in str(refused.value)


INQUIRY: dict[str, Any] = {
    "inquiry_id": "inquiry-1",
    "actor_id": "actor-1",
    "execution_id": "exec-1",
    "objective": "find the absorption edge",
    "execution_step_count": 2,
    "status": "Open",
    "conclusion": None,
    "observed_step_count": None,
    "execution_ended": None,
    "proposal_id": None,
}


def _inquiry_keeper(
    *,
    inquiry: dict[str, Any] | None = None,
    posts: dict[str, CannedResponse] | None = None,
) -> tuple[HttpKeeper, CannedHttp]:
    http = CannedHttp(
        gets={"/inquiries/inquiry-1": CannedResponse(200, inquiry if inquiry else INQUIRY)},
        posts=posts
        or {
            "/inquiries": CannedResponse(201, {"inquiry_id": "inquiry-1"}),
            "/inquiries/inquiry-1/claim": CannedResponse(204),
            "/inquiries/inquiry-1/answer": CannedResponse(204),
        },
    )
    return HttpKeeper(http=http, base_url=BASE, token="a-token"), http


def test_ask_posts_the_execution_and_the_objective_and_no_time() -> None:
    """The keeper is the authority for when a question was put, because
    the call is the putting."""
    keeper, http = _inquiry_keeper()

    keeper.ask("exec-1", "find the edge")

    assert http.sent == [("/inquiries", {"execution_id": "exec-1", "objective": "find the edge"})]


def test_ask_returns_the_question_with_the_id_the_keeper_minted() -> None:
    """A whole question comes back, so a thinker that opened one holds
    what a thinker handed one holds."""
    keeper, _http = _inquiry_keeper()

    question = keeper.ask("exec-1", "find the edge")

    assert (question.inquiry_id, question.execution_id, question.objective) == (
        "inquiry-1",
        "exec-1",
        "find the edge",
    )


def test_ask_lets_a_refused_objective_through() -> None:
    """A question the record will not hold is not one to think about and
    then discover has nowhere to land."""
    keeper, _http = _inquiry_keeper(
        posts={"/inquiries": CannedResponse(400, text="objective is empty after trimming")}
    )

    with pytest.raises(RequestRefusedError):
        keeper.ask("exec-1", "   ")


def test_question_reads_the_execution_and_objective_off_the_record() -> None:
    keeper, _http = _inquiry_keeper()

    question = keeper.question("inquiry-1")

    assert (question.execution_id, question.objective) == (
        "exec-1",
        "find the absorption edge",
    )


def test_question_refuses_an_id_naming_no_inquiry() -> None:
    keeper, _http = _inquiry_keeper()

    with pytest.raises(RequestRefusedError):
        keeper.question("inquiry-absent")


def test_claim_reports_that_the_question_was_this_thinkers_to_take() -> None:
    keeper, _http = _inquiry_keeper()

    assert keeper.claim("inquiry-1") is True


def test_claim_reports_a_question_another_thinker_holds_without_raising() -> None:
    """409 is an ordinary outcome rather than a fault, and travels as
    False so a caller does not treat a healthy race as an outage."""
    keeper, _http = _inquiry_keeper(
        posts={"/inquiries/inquiry-1/claim": CannedResponse(409, text="not open")}
    )

    assert keeper.claim("inquiry-1") is False


def test_claim_raises_on_an_id_naming_no_inquiry() -> None:
    """Not a refusal to claim. Reporting a 404 as "somebody else has it"
    would send a caller looking for a thinker that does not exist."""
    keeper, _http = _inquiry_keeper(
        posts={"/inquiries/inquiry-1/claim": CannedResponse(404, text="no such inquiry")}
    )

    with pytest.raises(RequestRefusedError):
        keeper.claim("inquiry-1")


@pytest.mark.parametrize(
    ("conclusion", "word"),
    [
        (Propose("op-9", {"exposure": 2}, said="again"), "Propose"),
        (Stop(said="met"), "Stop"),
        (Abstain(said="nothing"), "Abstain"),
        (Refer(said="look"), "Refer"),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_answer_sends_each_conclusion_as_the_word_the_record_spells_it(
    conclusion: Conclusion, word: str
) -> None:
    keeper, http = _inquiry_keeper()

    keeper.answer(
        "inquiry-1", conclusion, Boundary(observed_step_count=2, execution_ended=True), None
    )

    assert http.sent[0][1] is not None
    assert http.sent[0][1]["conclusion"] == word


def test_answer_sends_the_observation_boundary_with_the_conclusion() -> None:
    """A conclusion nobody can weigh is what recording the boundary was
    meant to prevent, so it travels on the same request."""
    keeper, http = _inquiry_keeper()

    keeper.answer(
        "inquiry-1",
        Stop(said="met"),
        Boundary(observed_step_count=1, execution_ended=False),
        None,
    )

    sent = http.sent[0][1]
    assert sent is not None
    assert (sent["observed_step_count"], sent["execution_ended"]) == (1, False)


def test_answer_names_the_proposal_on_the_arm_that_wrote_one() -> None:
    keeper, http = _inquiry_keeper()

    keeper.answer(
        "inquiry-1",
        Propose("op-9", {}, said="again"),
        Boundary(observed_step_count=2, execution_ended=True),
        "proposal-42",
    )

    sent = http.sent[0][1]
    assert sent is not None
    assert sent["proposal_id"] == "proposal-42"


def test_answer_sends_no_proposal_on_the_arms_that_wrote_none() -> None:
    keeper, http = _inquiry_keeper()

    keeper.answer(
        "inquiry-1",
        Abstain(said="nothing"),
        Boundary(observed_step_count=0, execution_ended=False),
        None,
    )

    sent = http.sent[0][1]
    assert sent is not None
    assert sent["proposal_id"] is None


def test_answer_lets_a_refused_answer_through() -> None:
    keeper, _http = _inquiry_keeper(
        posts={"/inquiries/inquiry-1/answer": CannedResponse(409, text="already answered")}
    )

    with pytest.raises(RequestRefusedError):
        keeper.answer(
            "inquiry-1",
            Stop(said="met"),
            Boundary(observed_step_count=2, execution_ended=True),
            None,
        )


def test_answer_refuses_a_conclusion_this_adapter_has_no_word_for() -> None:
    """A fifth conclusion has to be given a word deliberately. Falling back
    to the class name would send the record something it will refuse, or
    worse a word it happens to accept."""

    class Ponder(Stop):
        """A conclusion nothing has mapped."""

    keeper, _http = _inquiry_keeper()

    with pytest.raises(UnknownConclusionError):
        keeper.answer(
            "inquiry-1",
            Ponder(said="hmm"),
            Boundary(observed_step_count=2, execution_ended=True),
            None,
        )


def test_every_conclusion_class_has_a_word_in_this_adapter() -> None:
    """The check that keeps the mapping honest as the four change. It
    ranges over the union rather than a list written here, so a fifth
    conclusion fails this instead of failing at a beamline."""
    assert set(get_args(Conclusion)) == set(CONCLUSIONS)
