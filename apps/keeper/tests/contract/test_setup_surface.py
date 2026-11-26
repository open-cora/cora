"""Defining, revising, reading and listing setups over HTTP, through the app the process builds.

The unit tests drive the handlers directly, so neither can see the two
failures that live only on a route: a request field bound to the wrong
argument, and a domain error nobody registered a status code for. Every
refusal a setup can be given is walked here for the second reason, because
an unregistered one is a 500 and every other tier stays green.

The name is checked in two places on this path, and the two answer to
different callers. Its length is on the request model, so an over-long
name never reaches a command and gets FastAPI's 422. Its alphabet is only
in the value object, so a name outside it gets this context's 400. The
status is the only way to tell from outside which one fired.
"""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.execution.aggregates.setup import SETUP_NAME_MAX_LENGTH
from keeper.infrastructure.settings import Settings

pytestmark = pytest.mark.contract

_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "config": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$"},
        "override": {"type": "object"},
    },
}

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "rotation-axis": {"type": "number", "unit": {"system": "udunits", "code": "pixel"}},
        "binning": {"type": "integer", "enum": [1, 2, 4]},
    },
}

_SETTINGS: dict[str, Any] = {"rotation-axis": 1630.0, "binning": 2}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(environment="test")))


def _an_operation(client: TestClient, schema: dict[str, Any] | None = None) -> str:
    response = client.post(
        "/operations",
        json={"name": "process", "parameters_schema": schema or _PROCESS_SCHEMA},
    )
    assert response.status_code == 201, response.text
    operation_id: str = response.json()["operation_id"]
    return operation_id


def _body(operation_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "beamline": "2-bm",
        "operation_id": operation_id,
        "name": "tomo-default",
        "settings": _SETTINGS,
        "settings_schema": _SETTINGS_SCHEMA,
        **overrides,
    }


def _a_setup(client: TestClient, operation_id: str, **overrides: Any) -> str:
    response = client.post("/setups", json=_body(operation_id, **overrides))
    assert response.status_code == 201, response.text
    setup_id: str = response.json()["setup_id"]
    return setup_id


def test_a_defined_setup_reads_back_whole_at_revision_one(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        setup_id = _a_setup(client, operation_id)
        response = client.get(f"/setups/{setup_id}")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "setup_id": setup_id,
        "beamline": "2-bm",
        "operation_id": operation_id,
        "name": "tomo-default",
        "revision": 1,
        "settings": _SETTINGS,
        "settings_schema": _SETTINGS_SCHEMA,
    }


def test_the_settings_schema_reads_back_byte_for_byte(client: TestClient) -> None:
    """Not re-rendered on the way out. A caller checking an override against
    the settings schema locally has to be checking against the document this system
    holds."""
    ordered = {
        "properties": {"binning": {"enum": [1, 2, 4], "type": "integer"}},
        "type": "object",
        "$schema": "https://json-schema.org/draft/2020-12/schema",
    }
    with client:
        setup_id = _a_setup(
            client, _an_operation(client), settings={"binning": 2}, settings_schema=ordered
        )
        response = client.get(f"/setups/{setup_id}")

    assert response.json()["settings_schema"] == ordered


def test_revising_answers_created_with_the_revision_number(client: TestClient) -> None:
    with client:
        setup_id = _a_setup(client, _an_operation(client))
        revised = client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": 1,
                "settings": {**_SETTINGS, "rotation-axis": 1631.5},
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )
        read = client.get(f"/setups/{setup_id}")

    assert revised.status_code == 201, revised.text
    assert revised.json() == {"setup_id": setup_id, "revision": 2}
    assert read.json()["revision"] == 2
    assert read.json()["settings"]["rotation-axis"] == 1631.5


def test_an_earlier_revision_reads_back_as_it_was_written(client: TestClient) -> None:
    with client:
        setup_id = _a_setup(client, _an_operation(client))
        client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": 1,
                "settings": {**_SETTINGS, "rotation-axis": 1631.5},
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )
        first = client.get(f"/setups/{setup_id}", params={"revision": 1})

    assert first.status_code == 200, first.text
    assert (first.json()["revision"], first.json()["settings"]) == (1, _SETTINGS)


def test_reading_a_revision_the_setup_has_not_reached_is_not_found(client: TestClient) -> None:
    with client:
        setup_id = _a_setup(client, _an_operation(client))
        response = client.get(f"/setups/{setup_id}", params={"revision": 2})

    assert response.status_code == 404, response.text
    assert "run from 1 to 1" in response.json()["detail"]


def test_asking_for_revision_zero_is_refused_by_the_surface(client: TestClient) -> None:
    with client:
        setup_id = _a_setup(client, _an_operation(client))
        response = client.get(f"/setups/{setup_id}", params={"revision": 0})

    assert response.status_code == 422, response.text


def test_reading_a_setup_that_was_never_defined_is_not_found(client: TestClient) -> None:
    with client:
        response = client.get(f"/setups/{uuid4()}")

    assert response.status_code == 404, response.text


def test_a_setup_for_an_operation_nobody_defined_is_not_found(client: TestClient) -> None:
    with client:
        response = client.post("/setups", json=_body(str(uuid4())))

    assert response.status_code == 404, response.text


def test_a_setup_for_a_retired_operation_is_a_conflict(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        client.post(f"/operations/{operation_id}/retire")
        response = client.post("/setups", json=_body(operation_id))

    assert response.status_code == 409, response.text
    assert operation_id in response.json()["detail"]


def test_a_setup_for_an_operation_that_takes_none_is_a_conflict(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(
            client, {"$schema": "https://json-schema.org/draft/2020-12/schema"}
        )
        response = client.post("/setups", json=_body(operation_id))

    assert response.status_code == 409, response.text
    assert "cannot take a setup" in response.json()["detail"]


def test_a_second_setup_under_a_held_key_is_a_conflict_naming_the_first(
    client: TestClient,
) -> None:
    with client:
        operation_id = _an_operation(client)
        first = _a_setup(client, operation_id)
        response = client.post("/setups", json=_body(operation_id))
        listed = client.get("/setups", params={"name": "tomo-default"}).json()

    assert response.status_code == 409, response.text
    assert first in response.json()["detail"]
    assert [item["setup_id"] for item in listed["items"]] == [first]


def test_a_name_outside_the_config_alphabet_is_a_bad_request(client: TestClient) -> None:
    """Within the length bound, so it passes the edge and is refused by the
    value object, which is what 400 rather than 422 says."""
    with client:
        response = client.post("/setups", json=_body(_an_operation(client), name="Tomo Default"))

    assert response.status_code == 400, response.text


def test_an_over_long_name_is_unprocessable(client: TestClient) -> None:
    with client:
        response = client.post(
            "/setups",
            json=_body(_an_operation(client), name="x" * (SETUP_NAME_MAX_LENGTH + 1)),
        )

    assert response.status_code == 422, response.text


def test_a_whitespace_only_beamline_is_a_bad_request(client: TestClient) -> None:
    with client:
        response = client.post("/setups", json=_body(_an_operation(client), beamline="   "))

    assert response.status_code == 400, response.text


def test_a_settings_schema_outside_the_subset_is_a_bad_request(client: TestClient) -> None:
    with client:
        response = client.post(
            "/setups",
            json=_body(
                _an_operation(client),
                settings_schema={**_SETTINGS_SCHEMA, "additionalProperties": False},
            ),
        )

    assert response.status_code == 400, response.text
    assert "forbidden keyword" in response.json()["detail"]


def test_a_setting_the_settings_schema_does_not_describe_is_a_bad_request(
    client: TestClient,
) -> None:
    with client:
        response = client.post(
            "/setups",
            json=_body(_an_operation(client), settings={**_SETTINGS, "filter": "Al"}),
        )

    assert response.status_code == 400, response.text
    assert "filter" in response.json()["detail"]


def test_a_body_with_no_settings_schema_is_unprocessable(client: TestClient) -> None:
    body = _body(str(uuid4()))
    del body["settings_schema"]
    with client:
        response = client.post("/setups", json=body)

    assert response.status_code == 422, response.text


def test_revisions_made_in_turn_against_the_latest_each_land(client: TestClient) -> None:
    """The number a revision answers with is the number the next one names.
    A route that sent the handler anything but the caller's own number would
    refuse the second of these or accept a stale one."""
    with client:
        setup_id = _a_setup(client, _an_operation(client))
        second = client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": 1,
                "settings": {**_SETTINGS, "binning": 4},
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )
        third = client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": second.json()["revision"],
                "settings": {**_SETTINGS, "binning": 1},
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )

    assert second.status_code == 201, second.text
    assert third.status_code == 201, third.text
    assert third.json() == {"setup_id": setup_id, "revision": 3}


def test_a_revision_made_against_an_older_revision_is_a_conflict_naming_both(
    client: TestClient,
) -> None:
    """The second caller read revision 1 and revises after the first caller
    already wrote revision 2. Refused, and told both numbers, so it can read
    again; the first caller's values are what the setup holds."""
    with client:
        setup_id = _a_setup(client, _an_operation(client))
        first = client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": 1,
                "settings": {**_SETTINGS, "binning": 4},
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )
        stale = client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": 1,
                "settings": {**_SETTINGS, "binning": 1},
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )
        read = client.get(f"/setups/{setup_id}")

    assert first.status_code == 201, first.text
    assert stale.status_code == 409, stale.text
    assert "made against revision 1, and the setup is at revision 2" in stale.json()["detail"]
    assert (read.json()["revision"], read.json()["settings"]["binning"]) == (2, 4)


def test_a_revision_body_with_no_expected_revision_is_unprocessable(client: TestClient) -> None:
    """Required, with no default: a revision that does not say what it was
    made against cannot be told apart from one made against nothing."""
    with client:
        setup_id = _a_setup(client, _an_operation(client))
        response = client.post(
            f"/setups/{setup_id}/revisions",
            json={"settings": {**_SETTINGS, "binning": 4}, "settings_schema": _SETTINGS_SCHEMA},
        )

    assert response.status_code == 422, response.text


def test_a_revision_that_changes_nothing_is_a_conflict(client: TestClient) -> None:
    with client:
        setup_id = _a_setup(client, _an_operation(client))
        response = client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": 1,
                "settings": _SETTINGS,
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )

    assert response.status_code == 409, response.text


def test_a_revision_whose_settings_do_not_match_is_a_bad_request(client: TestClient) -> None:
    with client:
        setup_id = _a_setup(client, _an_operation(client))
        response = client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": 1,
                "settings": {**_SETTINGS, "binning": 3},
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )

    assert response.status_code == 400, response.text


def test_revising_a_setup_nobody_defined_is_not_found(client: TestClient) -> None:
    with client:
        response = client.post(
            f"/setups/{uuid4()}/revisions",
            json={
                "expected_revision": 1,
                "settings": _SETTINGS,
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )

    assert response.status_code == 404, response.text


def test_a_listing_row_carries_exactly_the_fields_a_list_row_has(client: TestClient) -> None:
    """No settings and no settings schema, because a page of fifty would be a page
    of documents. Two timestamps, because a setup changes after it is
    defined."""
    with client:
        operation_id = _an_operation(client)
        setup_id = _a_setup(client, operation_id)
        client.post(
            f"/setups/{setup_id}/revisions",
            json={
                "expected_revision": 1,
                "settings": {**_SETTINGS, "binning": 4},
                "settings_schema": _SETTINGS_SCHEMA,
            },
        )
        body = client.get("/setups").json()

    (row,) = body["items"]
    assert set(body) == {"items", "next_cursor"}
    assert set(row) == {
        "setup_id",
        "beamline",
        "operation_id",
        "name",
        "revision",
        "created_at",
        "revised_at",
    }
    assert (row["setup_id"], row["operation_id"], row["revision"]) == (setup_id, operation_id, 2)


def test_listing_by_each_part_of_the_key_narrows_to_its_setups(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        other_operation = _an_operation(client)
        wanted = _a_setup(client, operation_id)
        elsewhere = _a_setup(client, operation_id, beamline="19-bm")
        for_another = _a_setup(client, other_operation)
        renamed = _a_setup(client, operation_id, name="tomo-binned")

        def ids(**params: str) -> list[str]:
            return [
                item["setup_id"] for item in client.get("/setups", params=params).json()["items"]
            ]

        by_beamline = ids(beamline="19-bm")
        by_operation = ids(operation_id=other_operation)
        by_name = ids(name="tomo-binned")
        by_key = ids(beamline="2-bm", operation_id=operation_id, name="tomo-default")

    assert by_beamline == [elsewhere]
    assert by_operation == [for_another]
    assert by_name == [renamed]
    assert by_key == [wanted]


def test_listing_by_a_name_no_setup_could_hold_is_a_bad_request(client: TestClient) -> None:
    with client:
        response = client.get("/setups", params={"name": "Tomo Default"})

    assert response.status_code == 400, response.text


def test_listing_by_an_operation_id_that_is_not_a_uuid_is_unprocessable(
    client: TestClient,
) -> None:
    with client:
        response = client.get("/setups", params={"operation_id": "process"})

    assert response.status_code == 422, response.text


def test_listing_setups_with_a_cursor_that_did_not_come_from_a_response_is_refused(
    client: TestClient,
) -> None:
    with client:
        response = client.get("/setups", params={"cursor": "not-a-cursor"})

    assert response.status_code == 422, response.text


def test_a_page_of_setups_hands_back_a_cursor_that_reaches_the_rest(client: TestClient) -> None:
    with client:
        operation_id = _an_operation(client)
        defined = [_a_setup(client, operation_id, name=f"s{i}") for i in range(3)]
        first = client.get("/setups", params={"limit": 2}).json()
        second = client.get("/setups", params={"limit": 2, "cursor": first["next_cursor"]}).json()

    walked = [item["setup_id"] for page in (first, second) for item in page["items"]]
    assert walked == list(reversed(defined))
    assert second["next_cursor"] is None
