"""API tests for unified local model health routes."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from agent33.api.routes.model_health import get_local_orchestration_readiness_service
from agent33.config import Settings
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.services.lm_studio_readiness import (
    LMStudioReadinessService,
    _LMStudioFetchResult,
)
from agent33.services.model_health import (
    LocalOrchestrationReadinessService,
    _LocalOrchestrationFetchResult,
)
from agent33.services.ollama_readiness import (
    OllamaReadinessService,
    _OllamaFetchResult,
)


class _OllamaSequenceFetcher:
    def __init__(self, responses: list[_OllamaFetchResult]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def __call__(self, url: str) -> _OllamaFetchResult:
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("No more Ollama responses configured")
        return self._responses.pop(0)


class _LMStudioSequenceFetcher:
    def __init__(self, responses: list[_LMStudioFetchResult]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def __call__(self, url: str) -> _LMStudioFetchResult:
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("No more LM Studio responses configured")
        return self._responses.pop(0)


class _LocalOrchestrationSequenceFetcher:
    def __init__(self, responses: list[_LocalOrchestrationFetchResult]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def __call__(self, url: str) -> _LocalOrchestrationFetchResult:
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("No more local orchestration responses configured")
        return self._responses.pop(0)


@pytest.fixture()
def operator_read_client() -> TestClient:
    token = create_access_token("op-reader", scopes=["operator:read"], tenant_id="test-tenant")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def no_auth_client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _restore_readiness_services() -> Any:
    original_ollama = getattr(app.state, "ollama_readiness_service", None)
    original_lm_studio = getattr(app.state, "lm_studio_readiness_service", None)
    original_local_orchestration = getattr(
        app.state,
        "local_orchestration_readiness_service",
        None,
    )
    if "ollama_readiness_service" in app.state._state:
        del app.state.ollama_readiness_service
    if "lm_studio_readiness_service" in app.state._state:
        del app.state.lm_studio_readiness_service
    if "local_orchestration_readiness_service" in app.state._state:
        del app.state.local_orchestration_readiness_service
    yield
    if original_ollama is not None:
        app.state.ollama_readiness_service = original_ollama
    elif "ollama_readiness_service" in app.state._state:
        del app.state.ollama_readiness_service
    if original_lm_studio is not None:
        app.state.lm_studio_readiness_service = original_lm_studio
    elif "lm_studio_readiness_service" in app.state._state:
        del app.state.lm_studio_readiness_service
    if original_local_orchestration is not None:
        app.state.local_orchestration_readiness_service = original_local_orchestration
    elif "local_orchestration_readiness_service" in app.state._state:
        del app.state.local_orchestration_readiness_service


def _ollama_tags_payload() -> dict[str, Any]:
    return {
        "models": [
            {
                "name": "qwen2.5-coder:7b",
                "size": 4_700_000_000,
                "details": {"parameter_size": "7B", "quantization_level": "Q4_K_M"},
            }
        ]
    }


def _lm_studio_models_payload() -> dict[str, Any]:
    return {
        "data": [
            {
                "id": "qwen2.5-coder-7b-instruct",
                "owned_by": "lmstudio",
                "context_length": 32_768,
            },
            {
                "id": "mistral-nemo-instruct",
                "owned_by": "lmstudio",
                "context_length": 128_000,
            },
        ]
    }


def _install_services(
    *,
    ollama_responses: list[_OllamaFetchResult],
    lm_studio_responses: list[_LMStudioFetchResult],
    local_orchestration_responses: list[_LocalOrchestrationFetchResult],
    local_orchestration_settings: Settings | None = None,
) -> tuple[_OllamaSequenceFetcher, _LMStudioSequenceFetcher, _LocalOrchestrationSequenceFetcher]:
    ollama_fetcher = _OllamaSequenceFetcher(ollama_responses)
    lm_studio_fetcher = _LMStudioSequenceFetcher(lm_studio_responses)
    local_orchestration_fetcher = _LocalOrchestrationSequenceFetcher(local_orchestration_responses)
    app.state.ollama_readiness_service = OllamaReadinessService(
        Settings(),
        fetcher=ollama_fetcher,
    )
    app.state.lm_studio_readiness_service = LMStudioReadinessService(
        Settings(),
        fetcher=lm_studio_fetcher,
    )
    app.state.local_orchestration_readiness_service = LocalOrchestrationReadinessService(
        local_orchestration_settings or Settings(),
        fetcher=local_orchestration_fetcher,
    )
    return ollama_fetcher, lm_studio_fetcher, local_orchestration_fetcher


class TestModelHealthRoute:
    def test_builds_the_local_orchestration_service_lazily(self) -> None:
        scope = {"type": "http", "app": app}
        request = Request(scope)
        if "local_orchestration_readiness_service" in app.state._state:
            del app.state.local_orchestration_readiness_service

        svc = get_local_orchestration_readiness_service(request)

        assert isinstance(svc, LocalOrchestrationReadinessService)
        assert app.state.local_orchestration_readiness_service is svc

    def test_requires_auth(self, no_auth_client: TestClient) -> None:
        resp = no_auth_client.get("/v1/model-health")
        assert resp.status_code == 401

    def test_summarizes_ready_local_runtimes(self, operator_read_client: TestClient) -> None:
        ollama_fetcher, lm_studio_fetcher, local_orchestration_fetcher = _install_services(
            ollama_responses=[_OllamaFetchResult(status_code=200, payload=_ollama_tags_payload())],
            lm_studio_responses=[
                _LMStudioFetchResult(status_code=200, payload=_lm_studio_models_payload())
            ],
            local_orchestration_responses=[
                _LocalOrchestrationFetchResult(
                    status_code=200,
                    payload={"data": [{"id": "qwen3-coder-next"}]},
                )
            ],
        )

        resp = operator_read_client.get("/v1/model-health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_state"] == "ready"
        assert data["provider_count"] == 3
        assert data["ready_provider_count"] == 3
        assert data["total_model_count"] == 4
        assert data["providers"][0]["provider"] == "ollama"
        assert data["providers"][0]["model_count"] == 1
        assert data["providers"][1]["provider"] == "lm-studio"
        assert data["providers"][1]["model_count"] == 2
        assert data["providers"][2]["provider"] == "local-orchestration"
        assert data["providers"][2]["label"] == "llama.cpp"
        assert data["providers"][2]["model_count"] == 1
        assert ollama_fetcher.calls == ["http://ollama:11434/api/tags"]
        assert lm_studio_fetcher.calls == ["http://localhost:1234/v1/models"]
        assert local_orchestration_fetcher.calls == ["http://host.docker.internal:8033/v1/models"]

    def test_task_routing_recommends_provider_from_health(
        self,
        operator_read_client: TestClient,
    ) -> None:
        _install_services(
            ollama_responses=[_OllamaFetchResult(status_code=200, payload=_ollama_tags_payload())],
            lm_studio_responses=[
                _LMStudioFetchResult(status_code=200, payload=_lm_studio_models_payload())
            ],
            local_orchestration_responses=[
                _LocalOrchestrationFetchResult(
                    status_code=200,
                    payload={"data": [{"id": "qwen3-coder-next"}]},
                )
            ],
        )

        resp = operator_read_client.post(
            "/v1/model-health/task-routing",
            json={"task_kind": "coding", "objective": "fix the failing tests"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["readiness"] == "ready"
        assert data["recommended_provider"] == "local-orchestration"
        assert data["recommended_model"] == "qwen3-coder-next"
        assert "llama3.2:3b" in data["fallback_models"]
        assert "coding task policy" in data["reason"]

    def test_judgment_panel_approves_when_ready_models_and_controls_exist(
        self,
        operator_read_client: TestClient,
    ) -> None:
        _install_services(
            ollama_responses=[_OllamaFetchResult(status_code=200, payload=_ollama_tags_payload())],
            lm_studio_responses=[
                _LMStudioFetchResult(status_code=200, payload=_lm_studio_models_payload())
            ],
            local_orchestration_responses=[
                _LocalOrchestrationFetchResult(
                    status_code=200,
                    payload={"data": [{"id": "qwen3-coder-next"}]},
                )
            ],
        )

        resp = operator_read_client.post(
            "/v1/model-health/judgment-panel",
            json={
                "proposal_id": "proposal-1",
                "title": "Promote guarded route",
                "summary": "Ship a reviewed API route.",
                "evidence": ["pytest://route"],
                "rollback_plan": "Revert the route commit.",
                "tests": ["pytest engine/tests/test_route.py"],
                "risk_notes": "No destructive migration.",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["readiness"] == "ready"
        assert data["consensus"] == "approve"
        assert data["ready_model_count"] == 3
        assert len(data["votes"]) == 2
        assert {vote["decision"] for vote in data["votes"]} == {"approve"}

    def test_judgment_panel_requires_multiple_ready_models(
        self,
        operator_read_client: TestClient,
    ) -> None:
        _install_services(
            ollama_responses=[_OllamaFetchResult(status_code=200, payload=_ollama_tags_payload())],
            lm_studio_responses=[_LMStudioFetchResult(status_code=None, error="offline")],
            local_orchestration_responses=[
                _LocalOrchestrationFetchResult(status_code=None, error="offline")
            ],
        )

        resp = operator_read_client.post(
            "/v1/model-health/judgment-panel",
            json={
                "proposal_id": "proposal-2",
                "title": "Risky change",
                "summary": "Needs review.",
                "evidence": ["pytest://route"],
                "rollback_plan": "Revert.",
                "tests": ["pytest"],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["readiness"] == "needs_setup"
        assert data["consensus"] == "unavailable"
        assert data["ready_model_count"] == 1
        assert "requires 2 ready model providers" in data["failure_reasons"][0]

    def test_reports_attention_when_runtime_has_no_models(
        self,
        operator_read_client: TestClient,
    ) -> None:
        _install_services(
            ollama_responses=[_OllamaFetchResult(status_code=200, payload={"models": []})],
            lm_studio_responses=[_LMStudioFetchResult(status_code=None, error="offline")],
            local_orchestration_responses=[
                _LocalOrchestrationFetchResult(status_code=None, error="offline")
            ],
        )

        resp = operator_read_client.get("/v1/model-health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_state"] == "needs_attention"
        assert data["summary"] == (
            "Local model setup needs attention. Install or load a model, or start "
            "Ollama, LM Studio, or the local orchestration server."
        )
        assert data["ready_provider_count"] == 0
        assert data["attention_provider_count"] == 1
        assert data["total_model_count"] == 0

    def test_applies_safe_provider_specific_overrides(
        self,
        operator_read_client: TestClient,
    ) -> None:
        ollama_fetcher, lm_studio_fetcher, local_orchestration_fetcher = _install_services(
            ollama_responses=[_OllamaFetchResult(status_code=200, payload=_ollama_tags_payload())],
            lm_studio_responses=[
                _LMStudioFetchResult(status_code=200, payload=_lm_studio_models_payload())
            ],
            local_orchestration_responses=[
                _LocalOrchestrationFetchResult(
                    status_code=200,
                    payload={"data": [{"id": "qwen3-coder-next"}]},
                )
            ],
        )

        resp = operator_read_client.get(
            "/v1/model-health",
            params={
                "ollama_base_url": "http://localhost:11434/v1",
                "lm_studio_base_url": "http://127.0.0.1:1234",
                "local_orchestration_base_url": "http://localhost:8033",
            },
        )

        assert resp.status_code == 200
        assert resp.json()["overall_state"] == "ready"
        assert ollama_fetcher.calls == ["http://localhost:11434/api/tags"]
        assert lm_studio_fetcher.calls == ["http://127.0.0.1:1234/v1/models"]
        assert local_orchestration_fetcher.calls == ["http://localhost:8033/v1/models"]

    def test_unsafe_override_is_reported_without_fetching_provider(
        self,
        operator_read_client: TestClient,
    ) -> None:
        ollama_fetcher, lm_studio_fetcher, local_orchestration_fetcher = _install_services(
            ollama_responses=[_OllamaFetchResult(status_code=200, payload=_ollama_tags_payload())],
            lm_studio_responses=[
                _LMStudioFetchResult(status_code=200, payload=_lm_studio_models_payload())
            ],
            local_orchestration_responses=[
                _LocalOrchestrationFetchResult(
                    status_code=200,
                    payload={"data": [{"id": "qwen3-coder-next"}]},
                )
            ],
        )

        resp = operator_read_client.get(
            "/v1/model-health",
            params={
                "ollama_base_url": "http://metadata.google.internal/computeMetadata/v1",
                "lm_studio_base_url": "http://localhost:1234/v1",
                "local_orchestration_base_url": "http://metadata.google.internal/computeMetadata/v1",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["overall_state"] == "ready"
        assert data["providers"][0]["state"] == "error"
        assert "base URL overrides" in data["providers"][0]["message"]
        assert data["providers"][2]["state"] == "error"
        assert "base URL overrides" in data["providers"][2]["message"]
        assert ollama_fetcher.calls == []
        assert lm_studio_fetcher.calls == ["http://localhost:1234/v1/models"]
        assert local_orchestration_fetcher.calls == []

    def test_uses_engine_label_for_local_orchestration_runtime(
        self,
        operator_read_client: TestClient,
    ) -> None:
        _install_services(
            ollama_responses=[_OllamaFetchResult(status_code=200, payload={"models": []})],
            lm_studio_responses=[_LMStudioFetchResult(status_code=200, payload={"data": []})],
            local_orchestration_responses=[
                _LocalOrchestrationFetchResult(
                    status_code=200,
                    payload={"data": [{"id": "mixtral-8x7b"}]},
                )
            ],
            local_orchestration_settings=Settings(local_orchestration_engine="vLLM"),
        )

        resp = operator_read_client.get("/v1/model-health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["providers"][2]["provider"] == "local-orchestration"
        assert data["providers"][2]["label"] == "vLLM"

    def test_uses_the_startup_ollama_runtime_when_configured(
        self,
        operator_read_client: TestClient,
    ) -> None:
        _install_services(
            ollama_responses=[_OllamaFetchResult(status_code=200, payload={"models": []})],
            lm_studio_responses=[_LMStudioFetchResult(status_code=200, payload={"data": []})],
            local_orchestration_responses=[
                _LocalOrchestrationFetchResult(
                    status_code=200,
                    payload={"models": [{"name": "qwen3-coder:latest"}]},
                )
            ],
            local_orchestration_settings=Settings(
                local_orchestration_engine="ollama",
                local_orchestration_model="qwen3-coder",
            ),
        )

        resp = operator_read_client.get("/v1/model-health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["providers"][2]["provider"] == "local-orchestration"
        assert data["providers"][2]["label"] == "Ollama"
        assert data["providers"][2]["state"] == "available"
        assert data["providers"][2]["default_model"] == "qwen3-coder"
        assert data["providers"][2]["base_url"] == "http://ollama:11434"
        assert data["providers"][2]["message"] == "Detected 1 startup Ollama model."
