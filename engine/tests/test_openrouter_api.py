"""API tests for OpenRouter setup UX routes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agent33.config import Settings
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.services.openrouter_catalog import OpenRouterCatalogService, _FetchResult


def _sample_catalog_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "id": "openai/gpt-5.5",
                "name": "OpenAI: GPT-5.5",
                "description": "Flagship reasoning model",
                "context_length": 1050000,
                "architecture": {
                    "modality": "text+image->text",
                    "input_modalities": ["text", "image"],
                    "output_modalities": ["text"],
                },
                "pricing": {
                    "prompt": "0.000005",
                    "completion": "0.00003",
                    "input_cache_read": "0.0000005",
                },
                "top_provider": {
                    "context_length": 1050000,
                    "max_completion_tokens": 128000,
                    "is_moderated": True,
                },
                "per_request_limits": {"requests_per_minute": 60},
                "supported_parameters": ["tool_choice", "tools", "structured_outputs"],
                "default_parameters": {},
                "links": {"details": "/api/v1/models/openai/gpt-5.5/endpoints"},
            }
        ]
    }


class _SequenceFetcher:
    def __init__(self, responses: list[_FetchResult]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def __call__(self, url: str, headers: dict[str, str]) -> _FetchResult:
        self.calls.append((url, headers))
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
def _restore_openrouter_service() -> Any:
    original = getattr(app.state, "openrouter_service", None)
    if "openrouter_service" in app.state._state:
        del app.state.openrouter_service
    yield
    if original is not None:
        app.state.openrouter_service = original
    else:
        if "openrouter_service" in app.state._state:
            del app.state.openrouter_service


def _service(
    responses: list[_FetchResult],
    *,
    api_key: str = "",
    ttl_seconds: int = 60,
) -> tuple[OpenRouterCatalogService, _SequenceFetcher]:
    settings = Settings()
    if api_key:
        object.__setattr__(settings, "openrouter_api_key", SecretStr(api_key))
    fetcher = _SequenceFetcher(responses)
    return OpenRouterCatalogService(settings, fetcher=fetcher, ttl_seconds=ttl_seconds), fetcher


class TestOpenRouterRouteAuth:
    def test_models_requires_auth(self, no_auth_client: TestClient) -> None:
        resp = no_auth_client.get("/v1/openrouter/models")
        assert resp.status_code == 401

    def test_probe_requires_auth(self, no_auth_client: TestClient) -> None:
        resp = no_auth_client.post("/v1/openrouter/probe")
        assert resp.status_code == 401


class TestOpenRouterModelsRoute:
    def test_returns_normalized_catalog(self, operator_read_client: TestClient) -> None:
        service, _ = _service([_FetchResult(status_code=200, payload=_sample_catalog_payload())])
        app.state.openrouter_service = service

        resp = operator_read_client.get("/v1/openrouter/models")

        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "openrouter"
        assert data["cached"] is False
        assert data["count"] == 1
        model = data["models"][0]
        assert model["id"] == "openai/gpt-5.5"
        assert model["provider"] == "openai"
        assert model["vendor"] == "openai"
        assert model["pricing"]["prompt"] == 0.000005
        assert model["pricing"]["completion"] == 0.00003
        assert model["pricing"]["cache_read"] == 0.0000005
        assert model["capabilities"]["supports_tools"] is True
        assert model["capabilities"]["supports_structured_outputs"] is True
        assert model["moderated"] is True

    def test_reuses_service_cache(self, operator_read_client: TestClient) -> None:
        service, fetcher = _service(
            [_FetchResult(status_code=200, payload=_sample_catalog_payload())]
        )
        app.state.openrouter_service = service

        first = operator_read_client.get("/v1/openrouter/models")
        second = operator_read_client.get("/v1/openrouter/models")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["cached"] is False
        assert second.json()["cached"] is True
        assert len(fetcher.calls) == 1


class TestOpenRouterProbeRoute:
    def test_reports_unconfigured_without_api_key(self, operator_read_client: TestClient) -> None:
        service, _ = _service([_FetchResult(status_code=200, payload=_sample_catalog_payload())])
        app.state.openrouter_service = service

        resp = operator_read_client.post("/v1/openrouter/probe")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "unconfigured"
        assert data["configured"] is False
        assert data["catalog"]["status"] == "ok"
        assert data["authenticated"]["status"] == "unconfigured"

    def test_reports_connected_with_valid_key(self, operator_read_client: TestClient) -> None:
        service, fetcher = _service(
            [
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
            ],
            api_key="sk-or-test",
        )
        app.state.openrouter_service = service

        resp = operator_read_client.post("/v1/openrouter/probe")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "connected"
        assert data["authenticated"]["status"] == "ok"
        assert fetcher.calls[1][1]["Authorization"] == "Bearer sk-or-test"

    def test_reports_configured_when_authenticated_check_fails(
        self,
        operator_read_client: TestClient,
    ) -> None:
        service, _ = _service(
            [
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
                _FetchResult(status_code=401, payload={"error": "Invalid API key"}),
            ],
            api_key="sk-or-test",
        )
        app.state.openrouter_service = service

        resp = operator_read_client.post("/v1/openrouter/probe")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "configured"
        assert data["authenticated"]["status"] == "error"
        assert data["authenticated"]["http_status"] == 401
        assert data["authenticated"]["detail"] == "Invalid API key"

    def test_probe_uses_request_overrides(self, operator_read_client: TestClient) -> None:
        service, fetcher = _service(
            [
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
                _FetchResult(status_code=200, payload=_sample_catalog_payload()),
            ]
        )
        app.state.openrouter_service = service

        resp = operator_read_client.post(
            "/v1/openrouter/probe",
            json={
                "openrouter_api_key": "sk-or-draft",
                "openrouter_base_url": "https://openrouter.ai/api/v1",
                "openrouter_site_url": "https://draft.agent33.example",
                "openrouter_app_name": "Draft Console",
                "openrouter_app_category": "draft-ui",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "connected"
        assert fetcher.calls[0][0] == "https://openrouter.ai/api/v1/models"
        assert fetcher.calls[0][1]["HTTP-Referer"] == "https://draft.agent33.example"
        assert fetcher.calls[1][1]["Authorization"] == "Bearer sk-or-draft"
        assert fetcher.calls[1][1]["X-OpenRouter-Title"] == "Draft Console"

    def test_models_returns_bad_gateway_on_upstream_failure(
        self,
        operator_read_client: TestClient,
    ) -> None:
        service, _ = _service([_FetchResult(status_code=503, detail="catalog down")])
        app.state.openrouter_service = service

        resp = operator_read_client.get("/v1/openrouter/models")

        assert resp.status_code == 502
        assert "HTTP 503" in resp.json()["detail"]
