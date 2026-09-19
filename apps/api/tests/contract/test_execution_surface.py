"""Writing and reading a plan over HTTP, through the app the process builds.

The unit tests exercise the handlers directly and the integration tests
exercise them against real SQL. Neither goes through a route, so neither
can see the two failures that live only there: a request field bound to
the wrong argument, and a domain error nobody registered a status code
for. Both leave every other tier green, and the second is a 500.

The name is checked twice on this path and the two checks answer to
different callers, so both are walked here. A name Pydantic can refuse
never reaches a command; one it cannot is refused by the value object
inside the decider. They produce different statuses, which is the only
way to tell from outside which one fired.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from aroc.api.main import create_app
from aroc.execution.aggregates.plan import PLAN_NAME_MAX_LENGTH
from aroc.infrastructure.settings import Settings

pytestmark = pytest.mark.contract

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def _a_plan(client: TestClient, name: str = "count") -> str:
    response = client.post("/plans", json={"name": name, "parameters_schema": _SCHEMA})
    assert response.status_code == 201, response.text
    plan_id: str = response.json()["plan_id"]
    return plan_id


def test_posting_a_plan_returns_its_id(client: TestClient) -> None:
    with client:
        assert _a_plan(client)


def test_a_defined_plan_reads_back_with_its_name_and_schema(client: TestClient) -> None:
    with client:
        plan_id = _a_plan(client)
        response = client.get(f"/plans/{plan_id}")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "plan_id": plan_id,
        "name": "count",
        "parameters_schema": _SCHEMA,
    }


def test_the_schema_reads_back_byte_for_byte(client: TestClient) -> None:
    """Not re-rendered on the way out, and this is what says so.

    A caller validating a request locally has to be validating against
    the same document this system will validate against. A route that
    rebuilt the schema from a parsed form, or dropped a keyword it did
    not recognise, would hand out a contract nothing enforces, and an
    equality on the whole dict is what notices.
    """
    ordered = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["exposure_seconds"],
        "properties": {"exposure_seconds": {"minimum": 0, "type": "number"}},
    }
    with client:
        created = client.post("/plans", json={"name": "count", "parameters_schema": ordered})
        plan_id = created.json()["plan_id"]
        response = client.get(f"/plans/{plan_id}")

    assert response.json()["parameters_schema"] == ordered


def test_reading_a_plan_that_was_never_defined_is_not_found(client: TestClient) -> None:
    with client:
        response = client.get("/plans/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_a_schema_outside_the_stored_subset_is_a_bad_request(client: TestClient) -> None:
    """The domain refusal, reached through the stack and mapped to a status.

    A decider raising the right error and a routes module that never
    learned about it both look correct in isolation, and together they
    are a 500.
    """
    with client:
        response = client.post(
            "/plans",
            json={"name": "count", "parameters_schema": {"type": "object"}},
        )
    assert response.status_code == 400, response.text


def test_a_whitespace_only_name_is_a_bad_request(client: TestClient) -> None:
    """Three spaces pass the length bound and are still not a name.

    Pydantic counts characters, so this body is well-formed as far as the
    edge can tell. The value object trims first and then counts, which is
    the check that catches it, and 400 rather than 422 is what says which
    of the two fired.
    """
    with client:
        response = client.post("/plans", json={"name": "   ", "parameters_schema": _SCHEMA})
    assert response.status_code == 400, response.text


def test_an_over_long_name_is_unprocessable(client: TestClient) -> None:
    """Refused at the edge, before a command is built.

    The other half of the pair above. This one never reaches the decider,
    so the status is FastAPI's own rather than one this context mapped.
    """
    with client:
        response = client.post(
            "/plans",
            json={"name": "x" * (PLAN_NAME_MAX_LENGTH + 1), "parameters_schema": _SCHEMA},
        )
    assert response.status_code == 422


def test_a_body_with_no_schema_is_unprocessable(client: TestClient) -> None:
    """Required, with no default, so omitting it is a malformed request.

    A plan whose parameters nobody described is the state the aggregate
    exists to refuse, and reaching it by leaving a key out would make the
    refusal look like a bug in the client.
    """
    with client:
        response = client.post("/plans", json={"name": "count"})
    assert response.status_code == 422


def _a_run(client: TestClient, plan_id: str, value: str = "f1e2d3c4") -> str:
    response = client.post(
        "/runs",
        json={
            "plan_id": plan_id,
            "parameters": {"exposure_seconds": 0.25},
            "external_ref": {"scheme": "bluesky-run-uid", "value": value},
        },
    )
    assert response.status_code == 201, response.text
    run_id: str = response.json()["run_id"]
    return run_id


def test_a_recorded_run_reads_back_with_its_plan_and_reference(client: TestClient) -> None:
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        response = client.get(f"/runs/{run_id}")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "run_id": run_id,
        "plan_id": plan_id,
        "parameters": {"exposure_seconds": 0.25},
        "external_ref": {"scheme": "bluesky-run-uid", "value": "f1e2d3c4"},
        "status": "Running",
    }


def test_the_run_response_carries_exactly_the_fields_a_run_has(client: TestClient) -> None:
    """The shape, pinned, so a field arrives deliberately rather than drifting.

    This used to assert there was no status, with a note saying it would
    fail the commit that added one and that that commit should read the
    note. It did, and this is it. The assertion is kept rather than
    deleted, because a response gaining a field nobody decided to add is
    the thing worth catching either way.
    """
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        body = client.get(f"/runs/{run_id}").json()

    assert set(body) == {"run_id", "plan_id", "parameters", "external_ref", "status"}
    assert body["status"] == "Running"


def test_recording_a_run_against_a_plan_that_does_not_exist_is_not_found(
    client: TestClient,
) -> None:
    """The handler's refusal, reached through the stack and given a status."""
    with client:
        response = client.post(
            "/runs",
            json={
                "plan_id": "00000000-0000-0000-0000-000000000000",
                "parameters": {"exposure_seconds": 0.25},
                "external_ref": {"scheme": "bluesky-run-uid", "value": "f1e2d3c4"},
            },
        )
    assert response.status_code == 404, response.text


def test_parameters_that_break_the_plans_schema_are_a_bad_request(client: TestClient) -> None:
    """The decider's refusal, which is a different status from the above.

    A plan that is not there and a plan that refuses the values are two
    different answers, and a caller needs to tell them apart: one means
    fix the id, the other means fix the values.
    """
    with client:
        plan_id = _a_plan(client)
        response = client.post(
            "/runs",
            json={
                "plan_id": plan_id,
                "parameters": {"exposure_seconds": -1},
                "external_ref": {"scheme": "bluesky-run-uid", "value": "f1e2d3c4"},
            },
        )
    assert response.status_code == 400, response.text


def test_a_whitespace_only_reference_value_is_a_bad_request(client: TestClient) -> None:
    """The shared value object's refusal, mapped by this context.

    `InvalidIdentifierError` belongs to a shared module rather than to an
    aggregate, so nothing else registers a status for it. Unregistered,
    this is a 500.
    """
    with client:
        plan_id = _a_plan(client)
        response = client.post(
            "/runs",
            json={
                "plan_id": plan_id,
                "parameters": {"exposure_seconds": 0.25},
                "external_ref": {"scheme": "bluesky-run-uid", "value": "   "},
            },
        )
    assert response.status_code == 400, response.text


def test_reading_a_run_that_was_never_recorded_is_not_found(client: TestClient) -> None:
    with client:
        response = client.get("/runs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("ending", "status"),
    [("complete", "Completed"), ("abort", "Aborted"), ("fail", "Failed")],
)
def test_each_ending_moves_the_run_to_its_own_status(
    client: TestClient, ending: str, status: str
) -> None:
    """Three endings, three statuses, one table.

    Parametrized rather than written three times, because the thing worth
    checking is that each path reaches its OWN terminal. Three separate
    tests would pass just as well if two of them were wired to the same
    handler, and the table is what makes that visible as two rows
    reporting one status.
    """
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        response = client.post(f"/runs/{run_id}/{ending}")
        after = client.get(f"/runs/{run_id}").json()

    assert response.status_code == 204, response.text
    assert after["status"] == status


@pytest.mark.parametrize("ending", ["complete", "abort", "fail"])
def test_ending_a_run_that_already_ended_is_a_conflict(client: TestClient, ending: str) -> None:
    """The domain refusal, reached through the stack and given a status.

    A decider raising the right error and a routes module that never
    learned about it both look correct in isolation, and together they
    are a 500. Three classes share this status and each is registered
    separately, so a missing entry shows up as one row failing.
    """
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        first = client.post(f"/runs/{run_id}/{ending}")
        second = client.post(f"/runs/{run_id}/{ending}")

    assert first.status_code == 204, first.text
    assert second.status_code == 409, second.text


def test_a_completed_run_cannot_then_be_failed(client: TestClient) -> None:
    """The endings refuse each other, not only themselves.

    An engine that reported success and then crashed on the way out looks
    exactly like this. The first ending stands and the disagreement
    surfaces as a conflict, rather than the second quietly overwriting a
    claim somebody already made.
    """
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        client.post(f"/runs/{run_id}/complete")
        response = client.post(f"/runs/{run_id}/fail")
        after = client.get(f"/runs/{run_id}").json()

    assert response.status_code == 409, response.text
    assert after["status"] == "Completed"


def test_ending_a_run_that_was_never_recorded_is_not_found(client: TestClient) -> None:
    """Existence is a different answer from a state that forbids the move."""
    with client:
        response = client.post("/runs/00000000-0000-0000-0000-000000000000/complete")
    assert response.status_code == 404


def test_a_run_that_pauses_and_resumes_comes_back_to_running(client: TestClient) -> None:
    """The one cycle in this machine, walked through the whole stack.

    Every other transition is one way, so this is the only place a status
    returns to a value it already held. Reading it at both points rather
    than only at the end is what distinguishes a working pair from a
    resume route wired to the pause handler, which would leave the run
    Paused, and from a pause that never fired, which would leave it
    Running throughout.
    """
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        paused = client.post(f"/runs/{run_id}/pause")
        during = client.get(f"/runs/{run_id}").json()["status"]
        resumed = client.post(f"/runs/{run_id}/resume")
        after = client.get(f"/runs/{run_id}").json()["status"]

    assert (paused.status_code, resumed.status_code) == (204, 204), paused.text
    assert (during, after) == ("Paused", "Running")


def test_a_paused_run_can_still_be_aborted(client: TestClient) -> None:
    """Pausing does not take the endings away, and this is what says so.

    `has_ended` used to read `status is not Running`, which was right
    while Running was the only live status. Left that way, adding Paused
    would have made every ending refuse here, and a paused run is the one
    an operator is most likely to abort.
    """
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        client.post(f"/runs/{run_id}/pause")
        response = client.post(f"/runs/{run_id}/abort")
        after = client.get(f"/runs/{run_id}").json()["status"]

    assert response.status_code == 204, response.text
    assert after == "Aborted"


@pytest.mark.parametrize(
    ("first", "second"),
    [("pause", "pause"), ("resume", "resume")],
)
def test_repeating_a_pause_or_a_resume_is_a_conflict(
    client: TestClient, first: str, second: str
) -> None:
    """Each of the pair refuses its own repeat, from opposite directions.

    The pause row starts from Running, takes the move and is refused the
    second time because the run is already Paused. The resume row is
    refused on the first call and again on the second, because the run
    was never paused at all. Both are 409, and both go through a class
    this module had to register: unregistered, either is a 500.
    """
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        client.post(f"/runs/{run_id}/{first}")
        response = client.post(f"/runs/{run_id}/{second}")

    assert response.status_code == 409, response.text


@pytest.mark.parametrize("move", ["pause", "resume"])
def test_pausing_or_resuming_a_run_that_already_ended_is_a_conflict(
    client: TestClient, move: str
) -> None:
    """A terminal closes the stream to the cycle as well as to the endings."""
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        client.post(f"/runs/{run_id}/complete")
        response = client.post(f"/runs/{run_id}/{move}")

    assert response.status_code == 409, response.text


@pytest.mark.parametrize("move", ["pause", "resume"])
def test_pausing_or_resuming_a_run_that_was_never_recorded_is_not_found(
    client: TestClient, move: str
) -> None:
    with client:
        response = client.post(f"/runs/00000000-0000-0000-0000-000000000000/{move}")
    assert response.status_code == 404


def test_a_run_reported_with_a_past_timestamp_is_accepted(client: TestClient) -> None:
    """A backfill, through the stack.

    The read model exposes no timestamp, so 201 is all this tier can see;
    that the stored row actually carries the reported instant is pinned
    against real SQL in the integration tier. What this adds is that the
    field survives the request model and reaches the command, which a
    body field bound to nothing would not.
    """
    with client:
        plan_id = _a_plan(client)
        response = client.post(
            "/runs",
            json={
                "plan_id": plan_id,
                "parameters": {"exposure_seconds": 0.25},
                "external_ref": {"scheme": "bluesky-run-uid", "value": "backfilled"},
                "occurred_at": "2019-03-04T09:30:00Z",
            },
        )

    assert response.status_code == 201, response.text


@pytest.mark.parametrize("ending", ["complete", "abort", "fail", "pause", "resume"])
def test_a_transition_accepts_a_reported_timestamp_in_its_body(
    client: TestClient, ending: str
) -> None:
    """The five endpoints that took no body at all now take an optional one.

    Parametrized because the body model is written five times, once per
    slice, and a slice whose route declared the field without passing it
    to the command would fail nowhere else. The resume row is expected to
    conflict rather than succeed, since the run is Running; what is being
    checked here is that the body parses and reaches the domain, and a
    409 proves that as well as a 204 does.
    """
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        response = client.post(
            f"/runs/{run_id}/{ending}",
            json={"occurred_at": "2019-03-04T09:30:00Z"},
        )

    expected = 409 if ending == "resume" else 204
    assert response.status_code == expected, response.text


@pytest.mark.parametrize("ending", ["complete", "abort", "fail", "pause", "resume"])
def test_a_transition_still_accepts_no_body_at_all(client: TestClient, ending: str) -> None:
    """The body stays optional, which is the compatibility promise.

    These endpoints published no body before. A caller that sends none
    must keep working, and gets the moment the report arrived.
    """
    with client:
        plan_id = _a_plan(client)
        run_id = _a_run(client, plan_id)
        response = client.post(f"/runs/{run_id}/{ending}")

    expected = 409 if ending == "resume" else 204
    assert response.status_code == expected, response.text


def test_a_timestamp_without_a_timezone_is_a_bad_request(client: TestClient) -> None:
    """The value object's refusal, reached through the stack and given a status.

    A naive datetime parses fine as far as Pydantic is concerned, so this
    is not a 422 from the edge. It is refused inside the command, and
    `InvalidOccurredAtError` had to be registered for 400 or this would
    be a 500.
    """
    with client:
        plan_id = _a_plan(client)
        response = client.post(
            "/runs",
            json={
                "plan_id": plan_id,
                "parameters": {"exposure_seconds": 0.25},
                "external_ref": {"scheme": "bluesky-run-uid", "value": "naive"},
                "occurred_at": "2019-03-04T09:30:00",
            },
        )

    assert response.status_code == 400, response.text


def test_a_retry_spelling_the_same_instant_differently_gets_the_first_run(
    client: TestClient,
) -> None:
    """Z and +00:00 are one instant, so they must be one command.

    The idempotency wrapper hashes the whole command, and this field
    joins that hash. Without the UTC conversion in `__post_init__` the
    two spellings would hash differently and the retry would come back
    422 rather than the run it already made.
    """
    headers = {"Idempotency-Key": "a-retried-report"}
    with client:
        plan_id = _a_plan(client)
        body = {
            "plan_id": plan_id,
            "parameters": {"exposure_seconds": 0.25},
            "external_ref": {"scheme": "bluesky-run-uid", "value": "retried"},
            "occurred_at": "2019-03-04T09:30:00Z",
        }
        first = client.post("/runs", json=body, headers=headers)
        second = client.post(
            "/runs", json={**body, "occurred_at": "2019-03-04T09:30:00+00:00"}, headers=headers
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["run_id"] == second.json()["run_id"]


def test_replaying_an_idempotency_key_returns_the_first_plan(client: TestClient) -> None:
    """A retry gets the plan it already made, not a second one."""
    body = {"name": "count", "parameters_schema": _SCHEMA}
    headers = {"Idempotency-Key": "a-retried-request"}
    with client:
        first = client.post("/plans", json=body, headers=headers)
        second = client.post("/plans", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["plan_id"] == second.json()["plan_id"]
