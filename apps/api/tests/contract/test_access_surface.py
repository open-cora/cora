"""Registering an actor over HTTP, through the app the process actually builds.

The unit tests exercise the handler directly. These go through the whole
stack: routing, body validation, the wire bundle, the idempotency wrapper
and the exception handlers. What they are really checking is that the
pieces were connected, which is the one thing a unit test cannot say.
"""

import pytest
from fastapi.testclient import TestClient

from aroc.access.aggregates.actor import ACTOR_NAME_MAX_LENGTH
from aroc.api.main import create_app
from aroc.infrastructure.settings import Settings

pytestmark = pytest.mark.contract


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def test_posting_a_name_creates_an_actor_and_returns_its_id(client: TestClient) -> None:
    with client:
        response = client.post("/actors", json={"name": "Ada Lovelace"})
    assert response.status_code == 201
    assert response.json()["actor_id"]


def test_two_posts_without_a_key_create_two_different_actors(client: TestClient) -> None:
    """The baseline the idempotency test below is measured against."""
    with client:
        first = client.post("/actors", json={"name": "Ada Lovelace"})
        second = client.post("/actors", json={"name": "Ada Lovelace"})
    assert first.json()["actor_id"] != second.json()["actor_id"]


def test_replaying_an_idempotency_key_returns_the_first_actor_again(
    client: TestClient,
) -> None:
    headers = {"Idempotency-Key": "a-client-supplied-retry-tag"}
    with client:
        first = client.post("/actors", json={"name": "Ada Lovelace"}, headers=headers)
        second = client.post("/actors", json={"name": "Ada Lovelace"}, headers=headers)
    assert first.status_code == 201
    assert second.json()["actor_id"] == first.json()["actor_id"]


def test_reusing_a_key_with_a_different_body_is_refused(client: TestClient) -> None:
    """A cached answer cannot be the right answer to a different question."""
    headers = {"Idempotency-Key": "a-client-supplied-retry-tag"}
    with client:
        client.post("/actors", json={"name": "Ada Lovelace"}, headers=headers)
        conflicting = client.post("/actors", json={"name": "Grace Hopper"}, headers=headers)
    assert conflicting.status_code == 422


def test_an_empty_name_is_rejected_by_the_body_schema(client: TestClient) -> None:
    with client:
        response = client.post("/actors", json={"name": ""})
    assert response.status_code == 422


def test_a_name_past_the_bound_is_rejected_by_the_body_schema(client: TestClient) -> None:
    with client:
        response = client.post("/actors", json={"name": "a" * (ACTOR_NAME_MAX_LENGTH + 1)})
    assert response.status_code == 422


def test_a_whitespace_only_name_is_rejected_by_the_domain(client: TestClient) -> None:
    """Past the schema, which only counts characters, and into the decider.

    A single space satisfies `min_length=1` and is empty once trimmed, so
    this is the case the body schema cannot catch and the value object can.
    """
    with client:
        response = client.post("/actors", json={"name": " "})
    assert response.status_code == 400


def test_the_created_actor_is_not_readable_yet(client: TestClient) -> None:
    """There is no read route. Stated so the gap is deliberate, not forgotten.

    Registering mints an identity and nothing yet reads one back, so the
    display name written to the vault is currently write-only. The read
    slice is the next one to land, and this assertion is what it deletes.
    """
    with client:
        created = client.post("/actors", json={"name": "Ada Lovelace"})
        response = client.get(f"/actors/{created.json()['actor_id']}")
    assert response.status_code == 404
