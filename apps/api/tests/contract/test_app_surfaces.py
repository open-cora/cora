"""The chassis serves its operational surfaces and nothing else.

These are the contract tests the baseline can actually make: the app boots,
both probes answer, metrics and the auth-discovery document are reachable, and
the OpenAPI document carries no domain. The last one is the interesting
assertion. It is what turns "we have not modelled anything yet" from a claim
into a check, so the first route that lands has to be added here deliberately.
"""

import pytest
from fastapi.testclient import TestClient

from aroc.api.main import create_app
from aroc.infrastructure.config import Settings

pytestmark = pytest.mark.contract

EXPECTED_OPENAPI_PATHS = frozenset(
    {
        "/health",
        "/.well-known/oauth-protected-resource",
    }
)
"""Every path the baseline publishes in its OpenAPI document.

`/readyz` and `/metrics` are absent deliberately: both are registered with
`include_in_schema=False` because they are operational endpoints, not part of
the API anyone codes against.

A bounded context adding its first route fails this test. That is the intent:
the addition should be visible in a diff rather than absorbed silently.
"""


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(settings=Settings(app_env="test")))


def test_health_returns_ok_without_touching_any_dependency(client: TestClient) -> None:
    with client:
        response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_readyz_reports_ready_with_no_pool_in_test_mode(client: TestClient) -> None:
    with client:
        response = client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    # `skipped`, not `ok`: test mode builds no pool, and the probe says so
    # rather than reporting a healthy database that does not exist.
    assert body["database"] == "skipped"
    assert body["app_env"] == "test"
    assert body["schema"] == "matched"


def test_readyz_reports_llm_off_when_no_key_is_configured(client: TestClient) -> None:
    with client:
        response = client.get("/readyz")
    assert response.json()["llm"] == "off"


def test_metrics_endpoint_counts_a_served_request(client: TestClient) -> None:
    with client:
        client.get("/health")
        response = client.get("/metrics")
    assert response.status_code == 200
    # /health is deliberately NOT in excluded_handlers: it is the sample
    # request that proves instrumentation is actually live, rather than
    # merely mounted.
    assert "/health" in response.text


def test_openapi_document_publishes_no_domain_paths(client: TestClient) -> None:
    with client:
        response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = frozenset(response.json()["paths"])
    assert paths == EXPECTED_OPENAPI_PATHS, (
        f"OpenAPI paths changed.\nAdded: {sorted(paths - EXPECTED_OPENAPI_PATHS)}\n"
        f"Removed: {sorted(EXPECTED_OPENAPI_PATHS - paths)}\n"
        "Update EXPECTED_OPENAPI_PATHS deliberately when a bounded context "
        "lands its first route."
    )


def test_protected_resource_metadata_is_discoverable(client: TestClient) -> None:
    with client:
        response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200


def test_oversized_request_body_is_rejected_with_413(client: TestClient) -> None:
    """The body-size cap runs before anything reads the body."""
    settings = Settings(app_env="test")
    oversized = b"x" * (settings.max_request_body_size_bytes + 1)
    with client:
        response = client.post("/health", content=oversized)
    assert response.status_code == 413
    assert "exceeds limit" in response.json()["detail"]
