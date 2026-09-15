"""Readiness rendering: the vocabulary is fixed and the body leaks nothing."""

import pytest
from pydantic import SecretStr

from aroc.api._readiness import derive_llm, readiness_body
from aroc.infrastructure.config import Settings

pytestmark = pytest.mark.unit


def test_readiness_body_reports_ready_when_the_database_probe_is_skipped() -> None:
    body = readiness_body("skipped", Settings(app_env="test"))
    assert body["status"] == "ready"


def test_readiness_body_reports_not_ready_when_the_database_is_unreachable() -> None:
    body = readiness_body("unreachable", Settings(app_env="local"))
    assert body["status"] == "not_ready"
    assert body["database"] == "unreachable"


def test_readiness_body_reports_ready_despite_a_degraded_schema() -> None:
    """A degraded process serves reads correctly, which is why it was allowed to boot.

    Reporting it unready would have an orchestrator pull it from rotation and
    remove the very access the override existed to grant.
    """
    body = readiness_body("ok", Settings(app_env="local"), "degraded")
    assert body["status"] == "ready"
    assert body["schema"] == "degraded"


def test_readiness_body_omits_the_database_url_and_error_text() -> None:
    """The endpoint is unauthenticated; the body must describe nothing."""
    settings = Settings(app_env="local", database_url="postgresql://secret:pw@db.internal/x")
    body = readiness_body("unreachable", settings)
    rendered = " ".join(body.values())
    assert "secret" not in rendered
    assert "db.internal" not in rendered
    assert "pw" not in rendered


def test_derive_llm_reports_off_when_enabled_without_a_key() -> None:
    """A deployment that sets the flag and forgets the credential calls nothing."""
    assert derive_llm(Settings(app_env="test", llm_enabled=True)) == "off"


def test_derive_llm_reports_live_only_with_both_the_flag_and_a_key() -> None:
    settings = Settings(app_env="test", llm_enabled=True, anthropic_api_key=SecretStr("sk-test"))
    assert derive_llm(settings) == "live"
