"""Registering an actor over HTTP, through the app the process actually builds.

The unit tests exercise the handler directly. These go through the whole
stack: routing, the wire bundle, the idempotency wrapper and the
exception handlers. What they are really checking is that the pieces were
connected, which is the one thing a unit test cannot say.

Registering takes no body, so there is nothing here about body
validation, and the idempotency CONFLICT path is not reachable from it
either: a command with no fields hashes one way. That case is pinned at
the unit tier against the wrapper itself, in
`tests/unit/test_idempotency_wrapper.py`.

Deactivating is not wrapped for idempotency at all. A replayed call is
refused by the domain, which is the 409 below.
"""

from uuid import uuid4

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


def test_deactivating_a_registered_actor_returns_no_content(client: TestClient) -> None:
    with client:
        created = client.post("/actors")
        response = client.post(f"/actors/{created.json()['actor_id']}/deactivate")
    assert response.status_code == 204


def test_deactivating_an_unknown_actor_is_a_not_found(client: TestClient) -> None:
    """The 404 handler, reached through the stack rather than asserted on a class."""
    with client:
        response = client.post(f"/actors/{uuid4()}/deactivate")
    assert response.status_code == 404


def test_deactivating_the_same_actor_twice_is_a_conflict(client: TestClient) -> None:
    """The domain refusal, reached through the stack and mapped to a status.

    Asserted here rather than only at the unit tier because the mapping
    is a separate registration in the routes module: a decider raising
    the right error and a route that never learned about it both look
    correct in isolation, and together they are a 500.
    """
    with client:
        created = client.post("/actors")
        actor_id = created.json()["actor_id"]
        client.post(f"/actors/{actor_id}/deactivate")
        second = client.post(f"/actors/{actor_id}/deactivate")
    assert second.status_code == 409


def test_a_malformed_actor_id_is_rejected_before_the_handler(client: TestClient) -> None:
    """The path parameter is a UUID, so the router refuses a non-UUID."""
    with client:
        response = client.post("/actors/not-a-uuid/deactivate")
    assert response.status_code == 422


def test_reactivating_a_deactivated_actor_returns_no_content(client: TestClient) -> None:
    with client:
        actor_id = client.post("/actors").json()["actor_id"]
        client.post(f"/actors/{actor_id}/deactivate")
        response = client.post(f"/actors/{actor_id}/reactivate")
    assert response.status_code == 204


def test_reactivating_an_actor_that_is_already_active_is_a_conflict(client: TestClient) -> None:
    with client:
        actor_id = client.post("/actors").json()["actor_id"]
        response = client.post(f"/actors/{actor_id}/reactivate")
    assert response.status_code == 409


def test_reactivating_an_unknown_actor_is_a_not_found(client: TestClient) -> None:
    with client:
        response = client.post(f"/actors/{uuid4()}/reactivate")
    assert response.status_code == 404


def test_the_two_switch_routes_reach_different_handlers(client: TestClient) -> None:
    """Both routes take the same path shape and return the same 204.

    A bundle field wired to the wrong handler, or a router registered
    twice under one function, would serve both paths from one slice.
    Deactivating then deactivating again is a conflict; deactivating
    then reactivating is not, and only distinct handlers give both.
    """
    with client:
        actor_id = client.post("/actors").json()["actor_id"]
        assert client.post(f"/actors/{actor_id}/deactivate").status_code == 204
        assert client.post(f"/actors/{actor_id}/deactivate").status_code == 409
        assert client.post(f"/actors/{actor_id}/reactivate").status_code == 204
        assert client.post(f"/actors/{actor_id}/reactivate").status_code == 409
