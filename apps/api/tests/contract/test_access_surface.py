"""Registering an actor over HTTP, through the app the process actually builds.

The unit tests exercise the handler directly. These go through the whole
stack: routing, the wire bundle, the idempotency wrapper and the
exception handlers. What they are really checking is that the pieces were
connected, which is the one thing a unit test cannot say.

There is no body, so there is nothing here about body validation. The
idempotency CONFLICT path is not reachable from this surface either, for
the same reason: a command with no fields hashes one way. That case is
pinned at the unit tier against the wrapper itself, in
`tests/unit/test_idempotency_wrapper.py`.
"""

import pytest
from fastapi.testclient import TestClient

from aroc.api.main import create_app
from aroc.infrastructure.settings import Settings

pytestmark = pytest.mark.contract


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def test_posting_to_actors_creates_one_and_returns_its_id(client: TestClient) -> None:
    with client:
        response = client.post("/actors")
    assert response.status_code == 201
    assert response.json()["actor_id"]


def test_two_posts_without_a_key_create_two_different_actors(client: TestClient) -> None:
    """The baseline the idempotency test below is measured against."""
    with client:
        first = client.post("/actors")
        second = client.post("/actors")
    assert first.json()["actor_id"] != second.json()["actor_id"]


def test_replaying_an_idempotency_key_returns_the_first_actor_again(
    client: TestClient,
) -> None:
    headers = {"Idempotency-Key": "a-client-supplied-retry-tag"}
    with client:
        first = client.post("/actors", headers=headers)
        second = client.post("/actors", headers=headers)
    assert first.status_code == 201
    assert second.json()["actor_id"] == first.json()["actor_id"]


def test_the_created_actor_is_not_readable_yet(client: TestClient) -> None:
    """There is no read route. Stated so the gap is deliberate, not forgotten.

    Registering mints an identity and nothing yet reads one back. The read
    slice is the next one to land, and this assertion is what it deletes.
    """
    with client:
        created = client.post("/actors")
        response = client.get(f"/actors/{created.json()['actor_id']}")
    assert response.status_code == 404
