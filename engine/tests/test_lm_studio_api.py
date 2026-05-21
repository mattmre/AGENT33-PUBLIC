"""API tests for LM Studio setup UX routes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent33.config import Settings
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.services.lm_studio_readiness import (
    LMStudioReadinessService,
    _LMStudioFetchResult,
    normalize_lm_studio_base_url,
)


class _SequenceFetcher:
    def __init__(self, responses: list[_LMStudioFetchResult]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def __call__(self, url: str) -> _LMStudioFetchResult:
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
def _restore_lm_studio_readiness_service() -> Any:
    original = getattr(app.state, "lm_studio_readiness_service", None)
    if "lm_studio_readiness_service" in app.state._state:
        del app.state.lm_studio_readiness_service
    yield
    if original is not None:
        app.state.lm_studio_readiness_service = original
    elif "lm_studio_readiness_service" in app.state._state:
        del app.state.lm_studio_readiness_service


def _sample_models_payload() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": "qwen2.5-coder-7b-instruct",
                "object": "model",
                "owned_by": "lmstudio",
                "created": 1_700_000_000,
                "context_length": 32_768,
            }
        ],
    }


def _service(
    responses: list[_LMStudioFetchResult],
) -> tuple[LMStudioReadinessService, _SequenceFetcher]:
    fetcher = _SequenceFetcher(responses)
    return LMStudioReadinessService(Settings(), fetcher=fetcher), fetcher


class TestLMStudioRouteAuth:
    def test_status_requires_auth(self, no_auth_client: TestClient) -> None:
        resp = no_auth_client.get("/v1/lm-studio/status")
        assert resp.status_code == 401

    def test_models_requires_auth(self, no_auth_client: TestClient) -> None:
        resp = no_auth_client.get("/v1/lm-studio/models")
        assert resp.status_code == 401


class TestLMStudioStatusRoute:
    def test_returns_available_models(self, operator_read_client: TestClient) -> None:
        service, fetcher = _service(
            [_LMStudioFetchResult(status_code=200, payload=_sample_models_payload())]
        )
        app.state.lm_studio_readiness_service = service

        resp = operator_read_client.get(
            "/v1/lm-studio/status",
            params={"base_url": "http://localhost:1234"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "lm-studio"
        assert data["state"] == "available"
        assert data["ok"] is True
        assert data["base_url"] == "http://localhost:1234/v1"
        assert data["count"] == 1
        assert data["models"][0]["name"] == "qwen2.5-coder-7b-instruct"
        assert data["models"][0]["context_length"] == 32_768
        assert fetcher.calls == ["http://localhost:1234/v1/models"]

    def test_reports_empty_model_store(self, operator_read_client: TestClient) -> None:
        service, _ = _service([_LMStudioFetchResult(status_code=200, payload={"data": []})])
        app.state.lm_studio_readiness_service = service

        resp = operator_read_client.get("/v1/lm-studio/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "empty"
        assert data["ok"] is False
        assert "no models" in data["message"]

    def test_reports_unreachable_lm_studio(self, operator_read_client: TestClient) -> None:
        service, _ = _service([_LMStudioFetchResult(status_code=None, error="connection refused")])
        app.state.lm_studio_readiness_service = service

        resp = operator_read_client.get("/v1/lm-studio/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "unavailable"
        assert data["ok"] is False
        assert "connection refused" in data["message"]

    def test_reports_malformed_payload(self, operator_read_client: TestClient) -> None:
        service, _ = _service([_LMStudioFetchResult(status_code=200, payload={"models": []})])
        app.state.lm_studio_readiness_service = service

        resp = operator_read_client.get("/v1/lm-studio/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "error"
        assert data["ok"] is False
        assert "unexpected payload" in data["message"]

    def test_blocks_unsafe_base_url_override(self, operator_read_client: TestClient) -> None:
        service, fetcher = _service(
            [_LMStudioFetchResult(status_code=200, payload=_sample_models_payload())]
        )
        app.state.lm_studio_readiness_service = service

        resp = operator_read_client.get(
            "/v1/lm-studio/status",
            params={"base_url": "http://metadata.google.internal/computeMetadata/v1"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "error"
        assert data["ok"] is False
        assert fetcher.calls == []

    def test_ignores_models_without_usable_ids(self, operator_read_client: TestClient) -> None:
        service, _ = _service(
            [_LMStudioFetchResult(status_code=200, payload={"data": [{"owned_by": "local"}]})]
        )
        app.state.lm_studio_readiness_service = service

        resp = operator_read_client.get("/v1/lm-studio/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "empty"
        assert data["count"] == 0

    def test_models_endpoint_returns_model_list(self, operator_read_client: TestClient) -> None:
        service, _ = _service(
            [_LMStudioFetchResult(status_code=200, payload=_sample_models_payload())]
        )
        app.state.lm_studio_readiness_service = service

        resp = operator_read_client.get("/v1/lm-studio/models")

        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "lm-studio"
        assert data["count"] == 1
        assert data["models"][0]["id"] == "qwen2.5-coder-7b-instruct"


def test_normalizes_lm_studio_base_url_for_openai_compatible_api() -> None:
    assert normalize_lm_studio_base_url("http://localhost:1234") == "http://localhost:1234/v1"
    assert normalize_lm_studio_base_url("http://localhost:1234/v1") == "http://localhost:1234/v1"
    assert normalize_lm_studio_base_url("http://localhost:1234/v1/") == "http://localhost:1234/v1"
