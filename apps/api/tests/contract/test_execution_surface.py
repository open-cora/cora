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
