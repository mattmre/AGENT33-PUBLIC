from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.compatibility.errors import (
    ProviderErrorClass,
    classify_provider_error,
    fallback_decision,
)
from agent33.main import app
from agent33.security.auth import create_access_token


def _client() -> TestClient:
    token = create_access_token("compat-user", scopes=["workflows:read"], tenant_id="tenant-a")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_provider_error_taxonomy_classifies_common_failures() -> None:
    assert (
        classify_provider_error("Unauthorized API key", status_code=401) == ProviderErrorClass.AUTH
    )
    assert (
        classify_provider_error("rate limit exceeded", status_code=429)
        == ProviderErrorClass.RATE_LIMIT
    )
    assert classify_provider_error("context length exceeded") == ProviderErrorClass.CONTEXT_LENGTH
    assert (
        classify_provider_error("model not found", status_code=404)
        == ProviderErrorClass.MODEL_UNAVAILABLE
    )
    assert (
        classify_provider_error("Ollama connection refused")
        == ProviderErrorClass.RUNTIME_UNAVAILABLE
    )


def test_fallback_decision_marks_transient_errors_retryable() -> None:
    decision = fallback_decision(ProviderErrorClass.RATE_LIMIT)

    assert decision.retryable is True
    assert decision.fallback_recommended is True
    assert decision.circuit_breaker_recommended is True


def test_error_classification_endpoint_returns_normalized_class() -> None:
    client = _client()

    response = client.post(
        "/v1/compatibility/errors/classify",
        json={"provider": "openrouter", "model": "model-a", "message": "quota exceeded"},
    )

    assert response.status_code == 200
    assert response.json()["error_class"] == "rate_limit"


def test_fallback_decision_endpoint_returns_policy() -> None:
    client = _client()

    response = client.get("/v1/compatibility/errors/decision/context_length")

    assert response.status_code == 200
    body = response.json()
    assert body["fallback_recommended"] is True
    assert body["retryable"] is False
