"""The keeper seam over HTTP: what it asks for, and what it makes of the answers."""

from __future__ import annotations

from typing import Any

import pytest

from tests._fakes import CannedHttp, CannedResponse
from thinker.adapters.keeper_http import HttpKeeper, RequestRefusedError

BASE = "https://keeper.example"

PROCEDURE: dict[str, Any] = {
    "procedure_id": "proc-1",
    "name": "an edge scan",
    "beamline": "2-BM",
    "steps": [
        {"kind": "move", "step_id": "s1", "record": "motor:x", "to": 1.5},
        {
            "kind": "acquire",
            "step_id": "s2",
            "plan_id": "plan-9",
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
            "describes": "acquire plan-9",
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


def test_propose_sends_the_plan_and_its_parameters() -> None:
    keeper, http = _keeper()
    keeper.propose("plan-9", {"exposure": 2})
    assert http.sent == [("/proposals", {"plan_id": "plan-9", "parameters": {"exposure": 2}})]


def test_propose_returns_the_id_the_keeper_gave_the_proposal() -> None:
    keeper, _ = _keeper(posts={"/proposals": CannedResponse(201, {"proposal_id": "proposal-42"})})
    assert keeper.propose("plan-9", {}) == "proposal-42"


def test_propose_lets_a_refusal_of_the_plans_schema_through() -> None:
    """A proposal that could not have run is worth more as an error than a row."""
    keeper, _ = _keeper(posts={"/proposals": CannedResponse(400, text="exposure must be a number")})
    with pytest.raises(RequestRefusedError) as refused:
        keeper.propose("plan-9", {"exposure": "two"})
    assert refused.value.status == 400
    assert "exposure must be a number" in str(refused.value)


def test_propose_refuses_an_answer_that_is_not_the_created_status() -> None:
    """200 on a route that creates something means the keeper is not the keeper."""
    keeper, _ = _keeper(posts={"/proposals": CannedResponse(200, {"proposal_id": "p"})})
    with pytest.raises(RequestRefusedError):
        keeper.propose("plan-9", {})


def test_a_refusal_names_the_method_and_path_that_drew_it() -> None:
    keeper, _ = _keeper(posts={"/proposals": CannedResponse(403, text="not granted")})
    with pytest.raises(RequestRefusedError) as refused:
        keeper.propose("plan-9", {})
    assert refused.value.method == "POST"
    assert refused.value.path == "/proposals"
    assert "POST /proposals: 403" in str(refused.value)
