"""Writing and reading an operation over HTTP, through the app the process builds.

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
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.execution.aggregates.operation import OPERATION_NAME_MAX_LENGTH
from keeper.infrastructure.settings import Settings

pytestmark = pytest.mark.contract

_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"exposure_seconds": {"type": "number", "minimum": 0}},
    "required": ["exposure_seconds"],
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(environment="test")))


def _an_operation(client: TestClient, name: str = "count") -> str:
    response = client.post("/operations", json={"name": name, "parameters_schema": _SCHEMA})
    assert response.status_code == 201, response.text
    operation_id: str = response.json()["operation_id"]
    return operation_id


def test_posting_a_plan_returns_its_id(client: TestClient) -> None:
    with client:
        assert _an_operation(client)


def test_a_defined_plan_reads_back_with_its_name_and_schema(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        response = client.get(f"/operations/{operation_id}")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "operation_id": operation_id,
        "name": "count",
        "parameters_schema": _SCHEMA,
        "status": "Active",
        "drives_devices": None,
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
        created = client.post("/operations", json={"name": "count", "parameters_schema": ordered})
        operation_id = created.json()["operation_id"]
        response = client.get(f"/operations/{operation_id}")

    assert response.json()["parameters_schema"] == ordered


def test_reading_a_plan_that_was_never_defined_is_not_found(client: TestClient) -> None:
    with client:
        response = client.get("/operations/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_a_schema_outside_the_stored_subset_is_a_bad_request(client: TestClient) -> None:
    """The domain refusal, reached through the stack and mapped to a status.

    A decider raising the right error and a routes module that never
    learned about it both look correct in isolation, and together they
    are a 500.
    """
    with client:
        response = client.post(
            "/operations",
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
        response = client.post("/operations", json={"name": "   ", "parameters_schema": _SCHEMA})
    assert response.status_code == 400, response.text


def test_an_over_long_name_is_unprocessable(client: TestClient) -> None:
    """Refused at the edge, before a command is built.

    The other half of the pair above. This one never reaches the decider,
    so the status is FastAPI's own rather than one this context mapped.
    """
    with client:
        response = client.post(
            "/operations",
            json={"name": "x" * (OPERATION_NAME_MAX_LENGTH + 1), "parameters_schema": _SCHEMA},
        )
    assert response.status_code == 422


def test_a_body_with_no_schema_is_unprocessable(client: TestClient) -> None:
    """Required, with no default, so omitting it is a malformed request.

    An operation whose parameters nobody described is the state the aggregate
    exists to refuse, and reaching it by leaving a key out would make the
    refusal look like a bug in the client.
    """
    with client:
        response = client.post("/operations", json={"name": "count"})
    assert response.status_code == 422


def _a_procedure(client: TestClient, name: str = "align_then_scan", beamline: str = "2-bm") -> str:
    """An operation and a procedure that sets once and runs once."""
    operation_id = _an_operation(client, name="tomo_scan")
    response = client.post(
        "/procedures",
        json={
            "name": name,
            "beamline": beamline,
            "steps": [
                {"kind": "set", "record": "2bmb:m1", "to": 0.0},
                {
                    "kind": "run",
                    "operation_id": operation_id,
                    "parameters": {"exposure_seconds": 0.1},
                    "scopes": ["2bmb:det:"],
                },
            ],
        },
    )
    assert response.status_code == 201, response.text
    procedure_id: str = response.json()["procedure_id"]
    return procedure_id


def _a_dispatch(client: TestClient, procedure_id: str) -> str:
    response = client.post("/executions", json={"procedure_id": procedure_id})
    assert response.status_code == 201, response.text
    execution_id: str = response.json()["execution_id"]
    return execution_id


def test_a_dispatched_execution_reads_back_with_its_procedure_and_steps(
    client: TestClient,
) -> None:
    with client:
        procedure_id = _a_procedure(client)
        execution_id = _a_dispatch(client, procedure_id)
        response = client.get(f"/executions/{execution_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["procedure_id"] == procedure_id
    assert body["procedure_name"] == "align_then_scan"
    assert body["status"] == "Dispatched"
    assert body["steps"][0]["describes"] == "set 2bmb:m1 to 0.0"


def test_the_execution_response_carries_exactly_the_fields_an_execution_has(
    client: TestClient,
) -> None:
    """The shape, pinned, so a field arrives deliberately rather than drifting."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        body = client.get(f"/executions/{execution_id}").json()

    assert set(body) == {
        "execution_id",
        "procedure_id",
        "procedure_name",
        "beamline",
        "status",
        "steps",
    }
    assert set(body["steps"][0]) == {
        "step_id",
        "describes",
        "procedure_step_id",
        "outcome",
        "engine_reference",
        "engine_state",
        "cause",
        "setup",
    }


def test_dispatching_a_procedure_that_does_not_exist_is_not_found(client: TestClient) -> None:
    """The handler's refusal, reached through the stack and given a status."""
    with client:
        response = client.post("/executions", json={"procedure_id": str(uuid4())})

    assert response.status_code == 404, response.text


def test_reading_an_execution_that_was_never_dispatched_is_not_found(client: TestClient) -> None:
    with client:
        response = client.get(f"/executions/{uuid4()}")

    assert response.status_code == 404, response.text


def test_a_claim_moves_a_dispatched_execution_and_a_second_one_is_a_conflict(
    client: TestClient,
) -> None:
    """The transient this context added, walked through the stack.

    Two drivers believing they own one traversal is what the Dispatched
    status exists to make visible, and the second claim being refused is
    the only place that shows.
    """
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        first = client.post(f"/executions/{execution_id}/claim")
        claimed = client.get(f"/executions/{execution_id}").json()["status"]
        second = client.post(f"/executions/{execution_id}/claim")

    assert (first.status_code, claimed, second.status_code) == (204, "Claimed", 409)


@pytest.mark.parametrize(
    ("outcome", "body"),
    [
        ("Done", {"outcome": "Done", "engine_reference": "uid-one"}),
        ("Refused", {"outcome": "Refused"}),
        ("Broken", {"outcome": "Broken", "cause": "MotorTimeout"}),
        ("Skipped", {"outcome": "Skipped"}),
    ],
)
def test_each_outcome_lands_on_the_step_it_names(
    client: TestClient, outcome: str, body: dict[str, Any]
) -> None:
    """Four outcomes, four shapes, one route.

    Parametrized because each outcome admits a different detail and the
    route binds all of them from one model, so a field bound to the wrong
    argument would show on one row and not the others.
    """
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        reported = client.post(f"/executions/{execution_id}/steps", json={**body, "index": 0})
        step = client.get(f"/executions/{execution_id}").json()["steps"][0]

    assert reported.status_code == 204, reported.text
    assert step["outcome"] == outcome


def test_reporting_one_step_twice_is_a_conflict(client: TestClient) -> None:
    """A step ends exactly once, and a second reading is either a repeated
    send or two drivers reporting one execution."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        client.post(f"/executions/{execution_id}/steps", json={"index": 0, "outcome": "Done"})
        again = client.post(
            f"/executions/{execution_id}/steps", json={"index": 0, "outcome": "Done"}
        )

    assert again.status_code == 409, again.text


def test_reporting_a_step_past_the_end_of_the_list_is_not_found(client: TestClient) -> None:
    """The step list is fixed at the genesis, so this means the caller and
    the record disagree about what is being walked."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(
            f"/executions/{execution_id}/steps", json={"index": 7, "outcome": "Done"}
        )

    assert response.status_code == 404, response.text


def test_a_detail_belonging_to_another_outcome_is_a_bad_request(client: TestClient) -> None:
    """Each outcome has exactly one shape, and dropping the extra quietly
    would lose whichever of the two was right."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(
            f"/executions/{execution_id}/steps",
            json={"index": 0, "outcome": "Done", "cause": "MotorTimeout"},
        )

    assert response.status_code == 400, response.text


def test_ending_an_execution_twice_is_a_conflict(client: TestClient) -> None:
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        first = client.post(f"/executions/{execution_id}/end")
        second = client.post(f"/executions/{execution_id}/end")

    assert (first.status_code, second.status_code) == (204, 409)


def test_something_arriving_after_an_execution_ended_is_a_conflict(client: TestClient) -> None:
    """An execution that has ended takes nothing further: the record is what
    it was when it closed, and a late step would rewrite history a reader
    may already have acted on."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        client.post(f"/executions/{execution_id}/end")
        late = client.post(
            f"/executions/{execution_id}/steps", json={"index": 0, "outcome": "Done"}
        )

    assert late.status_code == 409, late.text


@pytest.mark.parametrize("verb", ["claim", "end"])
def test_a_transition_accepts_a_reported_timestamp_in_its_body(
    client: TestClient, verb: str
) -> None:
    """The body model is written once per slice, so a slice whose route
    declared the field without passing it to the command would fail
    nowhere else."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(
            f"/executions/{execution_id}/{verb}",
            json={"occurred_at": "2019-03-04T09:30:00Z"},
        )

    assert response.status_code == 204, response.text


@pytest.mark.parametrize("verb", ["claim", "end"])
def test_a_transition_still_accepts_no_body_at_all(client: TestClient, verb: str) -> None:
    """The body stays optional. A caller that sends none gets the moment the
    report arrived."""
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(f"/executions/{execution_id}/{verb}")

    assert response.status_code == 204, response.text


def test_a_timestamp_without_a_timezone_is_a_bad_request(client: TestClient) -> None:
    """The value object's refusal, reached through the stack and given a status.

    A naive datetime parses fine as far as Pydantic is concerned, so this
    is not a 422 from the edge. It is refused inside the command, and
    `InvalidOccurredAtError` had to be registered for 400 or this would
    be a 500.
    """
    with client:
        execution_id = _a_dispatch(client, _a_procedure(client))
        response = client.post(
            f"/executions/{execution_id}/claim",
            json={"occurred_at": "2019-03-04T09:30:00"},
        )

    assert response.status_code == 400, response.text


def test_replaying_an_idempotency_key_returns_the_first_execution(client: TestClient) -> None:
    """A retry gets the execution it already dispatched, not a second one.

    Dispatching the same procedure again on purpose is an ordinary thing
    to do, so the key is what separates that from a retried request.
    """
    headers = {"Idempotency-Key": "a-retried-dispatch"}
    with client:
        body = {"procedure_id": _a_procedure(client)}
        first = client.post("/executions", json=body, headers=headers)
        second = client.post("/executions", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["execution_id"] == second.json()["execution_id"]


def test_listing_procedures_narrows_to_one_beamline_when_asked(
    client: TestClient,
) -> None:
    """The question an operator has, which this surface could not answer.

    FastAPI ignores a query parameter the route does not declare, so
    `?beamline=19-bm` used to come back as the whole facility with a 200
    on it. That reads as an answer, and the caller most likely to be
    fooled is one whose beamline genuinely holds most of the rows.
    """
    with client:
        here = _a_procedure(client, name="reconstruct", beamline="19-bm")
        _a_procedure(client, name="reconstruct", beamline="2-bm")
        response = client.get("/procedures", params={"beamline": "19-bm"})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["procedure_id"] for item in items] == [here]


def test_listing_procedures_by_beamline_and_name_narrows_by_both(
    client: TestClient,
) -> None:
    with client:
        _a_procedure(client, name="align", beamline="19-bm")
        wanted = _a_procedure(client, name="reconstruct", beamline="19-bm")
        _a_procedure(client, name="reconstruct", beamline="2-bm")
        response = client.get("/procedures", params={"beamline": "19-bm", "name": "reconstruct"})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["procedure_id"] for item in items] == [wanted]


def test_listing_procedures_for_a_beamline_with_none_returns_an_empty_page(
    client: TestClient,
) -> None:
    with client:
        _a_procedure(client, name="reconstruct", beamline="2-bm")
        response = client.get("/procedures", params={"beamline": "32-id"})

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_listing_procedures_refuses_a_blank_beamline_filter(
    client: TestClient,
) -> None:
    """A filter trimming to nothing is refused rather than read as absent.

    The alternative is the whole facility returned for a caller that
    plainly meant to narrow, which is the same wrong answer the missing
    parameter used to give.
    """
    with client:
        _a_procedure(client, name="reconstruct", beamline="2-bm")
        response = client.get("/procedures", params={"beamline": "   "})

    assert response.status_code == 400, response.text


def test_listing_executions_finds_the_ones_dispatched_for_a_procedure(
    client: TestClient,
) -> None:
    """A routine composed once is executed every time it runs, so many rows
    under one procedure is the ordinary case rather than a duplicate."""
    with client:
        procedure_id = _a_procedure(client)
        _a_dispatch(client, procedure_id)
        _a_dispatch(client, procedure_id)
        _a_dispatch(client, _a_procedure(client, name="something_else"))
        response = client.get("/executions", params={"procedure_id": procedure_id})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 2
    assert {item["procedure_id"] for item in items} == {procedure_id}


def test_the_work_intake_query_returns_only_what_this_beamline_has_not_taken_up(
    client: TestClient,
) -> None:
    """The request a conductor makes, through the stack rather than the port.

    Four executions: one at 7-BM, one at 2-BM already claimed, and two at
    2-BM still waiting. Only the two are work for a conductor at 2-BM,
    and either filter alone would hand it something it must not drive.
    """
    with client:
        here = _a_procedure(client, name="align_here", beamline="2-bm")
        elsewhere = _a_procedure(client, name="align_there", beamline="7-bm")
        waiting = [_a_dispatch(client, here), _a_dispatch(client, here)]
        _a_dispatch(client, elsewhere)
        claimed = _a_dispatch(client, here)
        assert client.post(f"/executions/{claimed}/claim").status_code == 204

        response = client.get("/executions", params={"beamline": "2-bm", "status": "Dispatched"})

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert {item["execution_id"] for item in items} == set(waiting)
    assert all(item["beamline"] == "2-bm" for item in items)


def test_an_idle_beamline_asking_for_work_gets_an_empty_page_not_a_refusal(
    client: TestClient,
) -> None:
    """What a conductor gets most of the time it asks."""
    with client:
        _a_dispatch(client, _a_procedure(client, beamline="2-bm"))
        response = client.get("/executions", params={"beamline": "32-id", "status": "Dispatched"})

    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_a_wait_returns_at_once_when_there_is_already_work(client: TestClient) -> None:
    """The long poll only holds a request that would answer empty."""
    with client:
        dispatched = _a_dispatch(client, _a_procedure(client, beamline="2-bm"))
        response = client.get(
            "/executions",
            params={"beamline": "2-bm", "status": "Dispatched", "wait": 30},
        )

    assert response.status_code == 200, response.text
    assert [item["execution_id"] for item in response.json()["items"]] == [dispatched]


def test_a_wait_past_the_ceiling_is_refused_rather_than_silently_shortened(
    client: TestClient,
) -> None:
    """A caller that asked to hold a connection for an hour gets told no.

    Bounded at the boundary rather than clamped, because a clamp would
    have the caller believe it is waiting far longer than it is and
    treat every return as a real answer.
    """
    with client:
        response = client.get("/executions", params={"wait": 3600})

    assert response.status_code == 422, response.text


def test_asking_for_a_status_that_is_not_one_is_refused_at_the_boundary(
    client: TestClient,
) -> None:
    """The status is an enum on the query string, so a typo is a 422 from
    the boundary rather than a silent empty page that reads like no work."""
    with client:
        response = client.get("/executions", params={"status": "Dispatchd"})

    assert response.status_code == 422, response.text


def test_listing_executions_that_match_nothing_is_an_empty_page_not_a_refusal(
    client: TestClient,
) -> None:
    """An absence is an answer, not an error."""
    with client:
        response = client.get("/executions", params={"procedure_id": str(uuid4())})

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "next_cursor": None}


def test_listing_executions_with_a_cursor_that_did_not_come_from_a_response_is_refused(
    client: TestClient,
) -> None:
    """A cursor is opaque, and a caller that made one up is depending on an
    encoding this is free to change.

    422 rather than 400, because the refusal is registered at the
    composition root: `InvalidCursorError` belongs to infrastructure and
    every list endpoint in the tree answers with the same status.
    """
    with client:
        response = client.get("/executions", params={"cursor": "not-a-cursor"})

    assert response.status_code == 422, response.text


def test_asking_for_more_executions_than_a_page_holds_is_refused_by_the_surface(
    client: TestClient,
) -> None:
    """The bound is on the request model, so this is the edge refusing
    rather than the domain."""
    with client:
        response = client.get("/executions", params={"limit": 5000})

    assert response.status_code == 422, response.text


def test_replaying_an_idempotency_key_returns_the_first_plan(client: TestClient) -> None:
    """A retry gets the operation it already made, not a second one."""
    body = {"name": "count", "parameters_schema": _SCHEMA}
    headers = {"Idempotency-Key": "a-retried-request"}
    with client:
        first = client.post("/operations", json=body, headers=headers)
        second = client.post("/operations", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["operation_id"] == second.json()["operation_id"]


def test_listing_plans_finds_every_plan_written_down_under_a_name(
    client: TestClient,
) -> None:
    """A name may match more than one operation on purpose, so the endpoint
    returns however many there are. An adapter resolving a routine's name
    to an operation has to see both and decide, which it cannot do if this
    picks one."""
    with client:
        first = _an_operation(client)
        second = _an_operation(client)
        _an_operation(client, name="scan")
        response = client.get("/operations", params={"name": "count"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["operation_id"] for item in body["items"]] == [second, first]
    assert body["next_cursor"] is None


def test_a_plan_summary_carries_exactly_the_fields_a_list_row_has(
    client: TestClient,
) -> None:
    """The shape, pinned. No schema, because a page of fifty would be a
    page of schemas, and one timestamp because the two later events an
    operation can have, a declaration of its device use and its
    retirement, are each reported by a field of their own."""
    with client:
        _an_operation(client)
        body = client.get("/operations").json()

    (row,) = body["items"]
    assert set(body) == {"items", "next_cursor"}
    assert set(row) == {"operation_id", "name", "status", "drives_devices", "created_at"}
    assert row["name"] == "count"
    assert row["status"] == "Active"
    assert row["drives_devices"] is None


def _declare(client: TestClient, operation_id: str, body: Any) -> Any:
    return client.post(f"/operations/{operation_id}/device-use", json=body)


@pytest.mark.parametrize("drives_devices", [True, False])
def test_declaring_device_use_answers_no_content_and_reads_back_on_both_reads(
    client: TestClient, drives_devices: bool
) -> None:
    """Both ways, because a route that wrote a constant would pass either one alone."""
    with client:
        operation_id = _an_operation(client)
        declared = _declare(client, operation_id, {"drives_devices": drives_devices})
        read = client.get(f"/operations/{operation_id}").json()
        (row,) = client.get("/operations").json()["items"]

    assert declared.status_code == 204, declared.text
    assert read["drives_devices"] is drives_devices
    assert row["drives_devices"] is drives_devices


def test_declaring_device_use_a_second_time_is_a_conflict_even_when_it_agrees(
    client: TestClient,
) -> None:
    with client:
        operation_id = _an_operation(client)
        _declare(client, operation_id, {"drives_devices": False})
        again = _declare(client, operation_id, {"drives_devices": False})
        read = client.get(f"/operations/{operation_id}").json()

    assert again.status_code == 409, again.text
    assert "already declared drives_devices = false" in again.json()["detail"]
    assert read["drives_devices"] is False


def test_declaring_device_use_of_a_retired_operation_is_a_conflict(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        _retire(client, f"/operations/{operation_id}")
        response = _declare(client, operation_id, {"drives_devices": True})
        read = client.get(f"/operations/{operation_id}").json()

    assert response.status_code == 409, response.text
    assert "Retired" in response.json()["detail"]
    assert read["drives_devices"] is None


def test_declaring_device_use_of_an_operation_nobody_defined_is_not_found(
    client: TestClient,
) -> None:
    with client:
        response = _declare(client, str(uuid4()), {"drives_devices": True})

    assert response.status_code == 404, response.text


@pytest.mark.parametrize("body", [{}, {"drives_devices": "false"}, {"drives_devices": None}])
def test_a_declaration_that_is_not_a_boolean_is_refused_at_the_boundary(
    client: TestClient, body: dict[str, Any]
) -> None:
    """A string read the wrong way round would decide every later run's claims."""
    with client:
        operation_id = _an_operation(client)
        response = _declare(client, operation_id, body)
        read = client.get(f"/operations/{operation_id}").json()

    assert response.status_code == 422, response.text
    assert read["drives_devices"] is None


def _retire(client: TestClient, path: str) -> Any:
    return client.post(f"{path}/retire")


def test_retiring_an_operation_answers_no_content_and_reads_back_retired(
    client: TestClient,
) -> None:
    with client:
        operation_id = _an_operation(client)
        retired = _retire(client, f"/operations/{operation_id}")
        read = client.get(f"/operations/{operation_id}")

    assert retired.status_code == 204, retired.text
    assert read.status_code == 200, read.text
    assert read.json()["status"] == "Retired"
    assert read.json()["parameters_schema"] == _SCHEMA


def test_retiring_an_operation_twice_is_a_conflict(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        _retire(client, f"/operations/{operation_id}")
        again = _retire(client, f"/operations/{operation_id}")

    assert again.status_code == 409, again.text


def test_retiring_an_operation_nobody_defined_is_not_found(client: TestClient) -> None:
    with client:
        response = _retire(client, f"/operations/{uuid4()}")

    assert response.status_code == 404, response.text


def test_a_retired_operation_is_listed_only_when_asked_for(client: TestClient) -> None:
    with client:
        kept = _an_operation(client, name="move")
        retired = _an_operation(client, name="transfer")
        _retire(client, f"/operations/{retired}")
        default = client.get("/operations").json()
        everything = client.get("/operations", params={"include_retired": True}).json()

    assert [item["operation_id"] for item in default["items"]] == [kept]
    assert {item["operation_id"]: item["status"] for item in everything["items"]} == {
        kept: "Active",
        retired: "Retired",
    }


def test_a_procedure_citing_a_retired_operation_is_a_conflict(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client, name="transfer")
        _retire(client, f"/operations/{operation_id}")
        response = client.post(
            "/procedures",
            json={
                "name": "Move a dataset",
                "beamline": "19-bm",
                "steps": [
                    {
                        "kind": "run",
                        "operation_id": operation_id,
                        "parameters": {"exposure_seconds": 0.1},
                        "drives_no_device": True,
                    }
                ],
            },
        )

    assert response.status_code == 409, response.text
    assert operation_id in response.json()["detail"]


def test_retiring_a_procedure_answers_no_content_and_reads_back_retired(
    client: TestClient,
) -> None:
    with client:
        procedure_id = _a_procedure(client)
        retired = _retire(client, f"/procedures/{procedure_id}")
        read = client.get(f"/procedures/{procedure_id}")

    assert retired.status_code == 204, retired.text
    assert read.json()["status"] == "Retired"
    assert len(read.json()["steps"]) == 2


def test_a_retired_procedure_is_listed_only_when_asked_for(client: TestClient) -> None:
    with client:
        kept = _a_procedure(client, name="Send a dataset", beamline="19-bm")
        retired = _a_procedure(client, name="Move a dataset", beamline="19-bm")
        _retire(client, f"/procedures/{retired}")
        default = client.get("/procedures", params={"beamline": "19-bm"}).json()
        everything = client.get(
            "/procedures", params={"beamline": "19-bm", "include_retired": True}
        ).json()

    assert [item["procedure_id"] for item in default["items"]] == [kept]
    assert {item["procedure_id"]: item["status"] for item in everything["items"]} == {
        kept: "Active",
        retired: "Retired",
    }


def test_dispatching_a_retired_procedure_is_a_conflict(client: TestClient) -> None:
    with client:
        procedure_id = _a_procedure(client)
        _retire(client, f"/procedures/{procedure_id}")
        response = client.post("/executions", json={"procedure_id": procedure_id})
        executions = client.get("/executions", params={"procedure_id": procedure_id}).json()

    assert response.status_code == 409, response.text
    assert executions["items"] == []


def test_dispatching_a_procedure_whose_operation_was_retired_is_a_conflict(
    client: TestClient,
) -> None:
    with client:
        procedure_id = _a_procedure(client)
        procedure = client.get(f"/procedures/{procedure_id}").json()
        (operation_id,) = [
            step["operation_id"] for step in procedure["steps"] if step["kind"] == "run"
        ]
        _retire(client, f"/operations/{operation_id}")
        response = client.post("/executions", json={"procedure_id": procedure_id})

    assert response.status_code == 409, response.text
    assert operation_id in response.json()["detail"]


def test_listing_plans_by_a_name_nothing_uses_is_an_empty_page(client: TestClient) -> None:
    with client:
        _an_operation(client)
        response = client.get("/operations", params={"name": "absent"})

    assert response.status_code == 200, response.text
    assert response.json() == {"items": [], "next_cursor": None}


def test_listing_plans_by_a_name_over_the_bound_is_refused(client: TestClient) -> None:
    """The filter goes through the same value object the defining command
    does, so a name no operation could carry is refused rather than quietly
    matching nothing."""
    with client:
        response = client.get("/operations", params={"name": "x" * 500})

    assert response.status_code == 400, response.text


def test_a_page_of_plans_hands_back_a_cursor_that_reaches_the_rest(
    client: TestClient,
) -> None:
    with client:
        defined = [_an_operation(client, name=f"p{i}") for i in range(3)]
        first = client.get("/operations", params={"limit": 2}).json()
        second = client.get(
            "/operations", params={"limit": 2, "cursor": first["next_cursor"]}
        ).json()

    walked = [item["operation_id"] for page in (first, second) for item in page["items"]]
    assert walked == list(reversed(defined))
    assert second["next_cursor"] is None


def _an_acquisition(client: TestClient) -> tuple[str, str]:
    """A dispatched execution and the id of its one run step."""
    operation_id = _an_operation(client, name="tomo_scan")
    defined = client.post(
        "/procedures",
        json={
            "name": "one_scan",
            "beamline": "2-bm",
            "steps": [
                {
                    "kind": "run",
                    "operation_id": operation_id,
                    "parameters": {"exposure_seconds": 0.1},
                    "scopes": ["2bmb:det:"],
                }
            ],
        },
    )
    assert defined.status_code == 201, defined.text
    dispatched = client.post("/executions", json={"procedure_id": defined.json()["procedure_id"]})
    assert dispatched.status_code == 201, dispatched.text
    execution_id: str = dispatched.json()["execution_id"]
    read = client.get(f"/executions/{execution_id}")
    step_id: str = read.json()["steps"][0]["step_id"]
    return execution_id, step_id


def test_an_engine_report_is_accepted_and_shows_on_the_step(client: TestClient) -> None:
    """The route a reporter posts every document to.

    Walked here because the engine state is the one field on a step that
    no other surface writes, so a body field bound to the wrong argument
    would leave every other tier green.
    """
    with client:
        execution_id, step_id = _an_acquisition(client)
        reported = client.post(
            f"/executions/{execution_id}/steps/{step_id}/run",
            json={"reported": "Started", "engine_reference": "uid-cycling"},
        )
        read = client.get(f"/executions/{execution_id}")

    assert reported.status_code == 204, reported.text
    step = read.json()["steps"][0]
    assert (step["engine_state"], step["engine_reference"]) == ("Running", "uid-cycling")


def test_a_report_that_does_not_follow_the_last_one_is_409(client: TestClient) -> None:
    """A redelivery is the case this status is chosen for.

    A reporter draining a document stream sends the same stop twice after
    any restart, and the second one is the system working. As a 400 it
    read as a malformed request, which is the one refusal a reporter must
    be able to tell apart from a bug in itself.
    """
    with client:
        execution_id, step_id = _an_acquisition(client)
        path = f"/executions/{execution_id}/steps/{step_id}/run"
        client.post(path, json={"reported": "Started"})
        client.post(path, json={"reported": "Completed"})
        again = client.post(path, json={"reported": "Completed"})

    assert again.status_code == 409, again.text
    assert "does not follow" in again.json()["detail"]


def test_an_engine_report_for_a_step_nobody_dispatched_is_404(client: TestClient) -> None:
    with client:
        execution_id, _step_id = _an_acquisition(client)
        response = client.post(
            f"/executions/{execution_id}/steps/{uuid4()}/run",
            json={"reported": "Started"},
        )

    assert response.status_code == 404, response.text


_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"config": {"type": "string"}, "override": {"type": "object"}},
}


def _settings_schema(*described: str) -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {name: {"type": "number"} for name in described},
    }


def _a_process(client: TestClient) -> str:
    response = client.post(
        "/operations", json={"name": "process", "parameters_schema": _PROCESS_SCHEMA}
    )
    assert response.status_code == 201, response.text
    operation_id: str = response.json()["operation_id"]
    return operation_id


def _a_setup(client: TestClient, operation_id: str) -> str:
    response = client.post(
        "/setups",
        json={
            "beamline": "2-bm",
            "operation_id": operation_id,
            "name": "tomo-default",
            "settings": {"rotation-axis": 1630.0, "binning": 2},
            "settings_schema": _settings_schema("rotation-axis", "binning"),
        },
    )
    assert response.status_code == 201, response.text
    setup_id: str = response.json()["setup_id"]
    return setup_id


def _revise_to(client: TestClient, setup_id: str, expected: int, *described: str) -> None:
    response = client.post(
        f"/setups/{setup_id}/revisions",
        json={
            "expected_revision": expected,
            "settings": dict.fromkeys(described, 1.0),
            "settings_schema": _settings_schema(*described),
        },
    )
    assert response.status_code == 201, response.text


def _post_processing(client: TestClient, operation_id: str) -> Any:
    """A procedure that sets once and then runs a step naming the setup."""
    return client.post(
        "/procedures",
        json={
            "name": "reconstruct",
            "beamline": "2-bm",
            "steps": [
                {"kind": "set", "record": "2bmb:m1", "to": 0.0},
                {
                    "kind": "run",
                    "operation_id": operation_id,
                    "parameters": {"config": "tomo-default", "override": {"binning": 4}},
                    "scopes": [],
                    "drives_no_device": True,
                },
            ],
        },
    )


def test_a_run_naming_a_setup_this_beamline_does_not_hold_is_a_bad_request(
    client: TestClient,
) -> None:
    """Registered, so the refusal is a 400 naming the setup rather than a 500."""
    with client:
        response = _post_processing(client, _a_process(client))

    assert response.status_code == 400, response.text
    assert "tomo-default" in response.json()["detail"]


def test_each_step_of_an_execution_reads_back_with_the_setup_it_was_pinned_to(
    client: TestClient,
) -> None:
    """Revised once after the procedure was defined, so the revision on the
    read is the one latest at dispatch. A set takes no setup and says null."""
    with client:
        operation_id = _a_process(client)
        setup_id = _a_setup(client, operation_id)
        defined = _post_processing(client, operation_id)
        assert defined.status_code == 201, defined.text
        _revise_to(client, setup_id, 1, "rotation-axis", "binning")
        execution_id = _a_dispatch(client, defined.json()["procedure_id"])

        steps = client.get(f"/executions/{execution_id}").json()["steps"]

    assert [step["setup"] for step in steps] == [
        None,
        {"setup_id": setup_id, "revision": 2},
    ]


def test_dispatching_once_a_revision_drops_a_setting_the_override_uses_is_a_conflict(
    client: TestClient,
) -> None:
    """A 409, because the procedure was accepted and the setup is what moved."""
    with client:
        operation_id = _a_process(client)
        setup_id = _a_setup(client, operation_id)
        defined = _post_processing(client, operation_id)
        assert defined.status_code == 201, defined.text
        _revise_to(client, setup_id, 1, "rotation-axis")

        response = client.post("/executions", json={"procedure_id": defined.json()["procedure_id"]})

    assert response.status_code == 409, response.text
    assert "binning" in response.json()["detail"]
