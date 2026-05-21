"""API tests for Ollama setup UX routes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent33.config import Settings
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.services.ollama_readiness import (
    OllamaReadinessService,
    _OllamaFetchResult,
    normalize_ollama_base_url,
)


class _SequenceFetcher:
    def __init__(self, responses: list[_OllamaFetchResult]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def __call__(self, url: str) -> _OllamaFetchResult:
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("No more fetcher responses configured")
        return self._responses.pop(0)


@pytest.fixture()
def operator_read_client() -> TestClient:
    token = create_access_token("op-reader", scopes=["operator:read"], tenant_id="test-tenant")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def no_auth_client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_ollama_readiness_service() -> Any:
    original = getattr(app.state, "ollama_readiness_service", None)
    if "ollama_readiness_service" in app.state._state:
        del app.state.ollama_readiness_service
    yield
    if original is not None:
        app.state.ollama_readiness_service = original
    elif "ollama_readiness_service" in app.state._state:
        del app.state.ollama_readiness_service


def _sample_tags_payload() -> dict[str, Any]:
    return {
        "models": [
            {
                "name": "qwen2.5-coder:7b",
                "model": "qwen2.5-coder:7b",
                "modified_at": "2026-04-29T08:00:00Z",
                "size": 4_700_000_000,
                "digest": "sha256:abc",
                "details": {
                    "family": "qwen2",
                    "families": ["qwen2"],
                    "format": "gguf",
                    "parameter_size": "7B",
                    "quantization_level": "Q4_K_M",
                },
            }
        ]
    }


def _service(
    responses: list[_OllamaFetchResult],
) -> tuple[OllamaReadinessService, _SequenceFetcher]:
    fetcher = _SequenceFetcher(responses)
    return OllamaReadinessService(Settings(), fetcher=fetcher), fetcher


class TestOllamaRouteAuth:
    def test_status_requires_auth(self, no_auth_client: TestClient) -> None:
        resp = no_auth_client.get("/v1/ollama/status")
        assert resp.status_code == 401

    def test_models_requires_auth(self, no_auth_client: TestClient) -> None:
        resp = no_auth_client.get("/v1/ollama/models")
        assert resp.status_code == 401


class TestOllamaStatusRoute:
    def test_returns_available_models(self, operator_read_client: TestClient) -> None:
        service, fetcher = _service(
            [_OllamaFetchResult(status_code=200, payload=_sample_tags_payload())]
        )
        app.state.ollama_readiness_service = service

        resp = operator_read_client.get(
            "/v1/ollama/status",
            params={"base_url": "http://localhost:11434/v1"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "ollama"
        assert data["state"] == "available"
        assert data["ok"] is True
        assert data["base_url"] == "http://localhost:11434"
        assert data["count"] == 1
        assert data["models"][0]["name"] == "qwen2.5-coder:7b"
        assert data["models"][0]["details"]["parameter_size"] == "7B"
        assert fetcher.calls == ["http://localhost:11434/api/tags"]

    def test_reports_empty_model_store(self, operator_read_client: TestClient) -> None:
        service, _ = _service([_OllamaFetchResult(status_code=200, payload={"models": []})])
        app.state.ollama_readiness_service = service

        resp = operator_read_client.get("/v1/ollama/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "empty"
        assert data["ok"] is False
        assert "no local models" in data["message"]

    def test_reports_unreachable_ollama(self, operator_read_client: TestClient) -> None:
        service, _ = _service([_OllamaFetchResult(status_code=None, error="connection refused")])
        app.state.ollama_readiness_service = service

        resp = operator_read_client.get("/v1/ollama/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "unavailable"
        assert data["ok"] is False
        assert "connection refused" in data["message"]

    def test_reports_malformed_payload(self, operator_read_client: TestClient) -> None:
        service, _ = _service([_OllamaFetchResult(status_code=200, payload={"unexpected": []})])
        app.state.ollama_readiness_service = service

        resp = operator_read_client.get("/v1/ollama/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "error"
        assert data["ok"] is False
        assert "unexpected payload" in data["message"]

    def test_blocks_unsafe_base_url_override(self, operator_read_client: TestClient) -> None:
        service, fetcher = _service(
            [_OllamaFetchResult(status_code=200, payload=_sample_tags_payload())]
        )
        app.state.ollama_readiness_service = service

        resp = operator_read_client.get(
            "/v1/ollama/status",
            params={"base_url": "http://metadata.google.internal/computeMetadata/v1"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "error"
        assert data["ok"] is False
        assert fetcher.calls == []

    def test_ignores_models_without_usable_names(self, operator_read_client: TestClient) -> None:
        service, _ = _service(
            [
                _OllamaFetchResult(
                    status_code=200,
                    payload={"models": [{"digest": "sha256:missing-name"}]},
                )
            ]
        )
        app.state.ollama_readiness_service = service

        resp = operator_read_client.get("/v1/ollama/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "empty"
        assert data["count"] == 0

    def test_models_endpoint_returns_model_list(self, operator_read_client: TestClient) -> None:
        service, _ = _service(
            [_OllamaFetchResult(status_code=200, payload=_sample_tags_payload())]
        )
        app.state.ollama_readiness_service = service

        resp = operator_read_client.get("/v1/ollama/models")

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "ollama"
        assert data["count"] == 1
        assert data["models"][0]["digest"] == "sha256:abc"


def test_normalizes_ollama_base_url_for_native_api() -> None:
    assert normalize_ollama_base_url("http://localhost:11434/v1") == "http://localhost:11434"
    assert normalize_ollama_base_url("http://localhost:11434/") == "http://localhost:11434"
