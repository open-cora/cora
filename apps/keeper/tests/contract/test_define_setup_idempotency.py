"""Replaying a setup's definition with the same retry key, over HTTP.

Defining a setup mints its id, so a retry with no key would be a second
setup, and the key check would then refuse it as taken. The wrapper is what
turns a retried request into the answer it already had rather than a
refusal naming itself. Both halves of its contract are here: the same body
gets the same setup back, and a different body under the same key is
refused rather than quietly answered with the first.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from keeper.api.main import create_app
from keeper.infrastructure.settings import Settings

pytestmark = pytest.mark.contract

_PROCESS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"config": {"type": "string"}, "override": {"type": "object"}},
}

_SETTINGS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {"rotation-axis": {"type": "number"}},
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(environment="test")))


def _body(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/operations", json={"name": "process", "parameters_schema": _PROCESS_SCHEMA}
    )
    assert response.status_code == 201, response.text
    return {
        "beamline": "2-bm",
        "operation_id": response.json()["operation_id"],
        "name": "tomo-default",
        "settings": {"rotation-axis": 1630.0},
        "settings_schema": _SETTINGS_SCHEMA,
    }


def test_replaying_an_idempotency_key_returns_the_first_setup(client: TestClient) -> None:
    """A retry gets the setup it already made. Without the wrapper it would
    reach the key check and be refused as a second setup under its own key."""
    headers = {"Idempotency-Key": "a-retried-definition"}
    with client:
        body = _body(client)
        first = client.post("/setups", json=body, headers=headers)
        second = client.post("/setups", json=body, headers=headers)
        listed = client.get("/setups").json()

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["setup_id"] == second.json()["setup_id"]
    assert [item["setup_id"] for item in listed["items"]] == [first.json()["setup_id"]]


def test_reusing_an_idempotency_key_for_a_different_setup_is_unprocessable(
    client: TestClient,
) -> None:
    headers = {"Idempotency-Key": "a-reused-key"}
    with client:
        body = _body(client)
        first = client.post("/setups", json=body, headers=headers)
        other = client.post("/setups", json={**body, "name": "tomo-binned"}, headers=headers)

    assert first.status_code == 201, first.text
    assert other.status_code == 422, other.text
