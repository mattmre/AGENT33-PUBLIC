"""Health endpoint tests."""

from __future__ import annotations

import contextlib
import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

import pytest
from pydantic import SecretStr

from agent33.api.routes import health as health_routes
from agent33.config import settings
from agent33.main import app


class _AsyncHealthService:
    def __init__(self, status: str) -> None:
        self._status = status

    async def health_snapshot(self) -> dict[str, str]:
        return {"status": self._status}


class _FakeAsyncClient:
    def __init__(
        self,
        response_codes: dict[str, int],
        response_payloads: dict[str, object],
        failures: set[str],
    ) -> None:
        self._response_codes = response_codes
        self._response_payloads = response_payloads
        self._failures = failures

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def get(self, url: str, headers=None):  # noqa: ANN001
        if url in self._failures:
            raise RuntimeError(f"forced failure for {url}")
        return SimpleNamespace(
            status_code=self._response_codes.get(url, 200),
            json=lambda: self._response_payloads.get(url, {}),
        )

    async def post(self, url: str, json=None, headers=None):  # noqa: ANN001
        if url in self._failures:
            raise RuntimeError(f"forced failure for {url}")
        return SimpleNamespace(
            status_code=self._response_codes.get(url, 200),
            json=lambda: self._response_payloads.get(url, {}),
        )


class _FakeRedisClient:
    async def ping(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


@pytest.fixture()
def health_http_state() -> dict[str, object]:
    return {"response_codes": {}, "response_payloads": {}, "failures": set()}


@pytest.fixture(autouse=True)
def _install_phase48_health_services(
    monkeypatch: pytest.MonkeyPatch,
    health_http_state: dict[str, object],
) -> None:
    original_voice = getattr(app.state, "voice_sidecar_probe", None)
    original_status_line = getattr(app.state, "status_line_service", None)
    app.state.voice_sidecar_probe = _AsyncHealthService("ok")
    app.state.status_line_service = _AsyncHealthService("ok")
    monkeypatch.setattr(
        "agent33.api.routes.health.httpx.AsyncClient",
        lambda timeout=3: _FakeAsyncClient(
            health_http_state["response_codes"],  # type: ignore[arg-type]
            health_http_state["response_payloads"],  # type: ignore[arg-type]
            health_http_state["failures"],  # type: ignore[arg-type]
        ),
    )
    monkeypatch.setattr(settings, "default_model", "openrouter/auto")
    monkeypatch.setattr(settings, "embedding_provider", "ollama")
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama:11434")
    monkeypatch.setattr(settings, "embedding_default_model", "nomic-embed-text")
    monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.com/v1")
    monkeypatch.setattr(settings, "openrouter_base_url", "https://openrouter.ai/api/v1")
    monkeypatch.setattr(settings, "openrouter_site_url", "http://localhost")
    monkeypatch.setattr(settings, "openrouter_app_name", "AGENT-33")
    monkeypatch.setattr(settings, "voice_daemon_transport", "stub")
    monkeypatch.setattr(settings, "voice_sidecar_url", "")
    monkeypatch.setattr(settings, "voice_tts_provider", "stub")
    monkeypatch.setattr(settings, "voice_elevenlabs_enabled", False)
    monkeypatch.setattr(settings, "jina_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "elevenlabs_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr("test-openai-key"))
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("test-openrouter-key"))
    response_payloads = health_http_state["response_payloads"]
    assert isinstance(response_payloads, dict)
    response_payloads[f"{settings.runtime_ollama_base_url}/api/tags"] = {
        "models": [{"name": settings.embedding_default_model}]
    }
    _fake_redis_async = SimpleNamespace(from_url=lambda *args, **kwargs: _FakeRedisClient())
    monkeypatch.setitem(
        sys.modules,
        "redis.asyncio",
        _fake_redis_async,
    )
    # When the real ``redis`` package has already been imported by an earlier
    # test (e.g. test_connection_pooling), ``import redis.asyncio as aioredis``
    # resolves through the parent module's attribute rather than
    # ``sys.modules["redis.asyncio"]``.  Patch the attribute on the parent
    # module so the fake is used regardless of prior import state.
    if "redis" in sys.modules:
        monkeypatch.setattr(sys.modules["redis"], "asyncio", _fake_redis_async)
    monkeypatch.setitem(
        sys.modules,
        "asyncpg",
        SimpleNamespace(
            connect=_fake_asyncpg_connect,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "nats",
        SimpleNamespace(connect=_fake_nats_connect),
    )
    yield
    if original_voice is not None:
        app.state.voice_sidecar_probe = original_voice
    else:
        with contextlib.suppress(AttributeError):
            del app.state.voice_sidecar_probe
    if original_status_line is not None:
        app.state.status_line_service = original_status_line
    else:
        with contextlib.suppress(AttributeError):
            del app.state.status_line_service


async def _fake_asyncpg_connect(*args, **kwargs):  # noqa: ANN002, ANN003
    class _Conn:
        async def execute(self, query: str) -> None:
            return None

        async def close(self) -> None:
            return None

    return _Conn()


async def _fake_nats_connect(*args, **kwargs):  # noqa: ANN002, ANN003
    class _Conn:
        async def close(self) -> None:
            return None

    return _Conn()


def test_health_returns_200(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] in ("healthy", "degraded")
    assert isinstance(data["services"], dict)
    assert isinstance(data["required_services"], dict)
    allowed_statuses = {"ok", "degraded", "unavailable", "configured", "unconfigured"}
    for svc_name, svc_status in data["services"].items():
        if svc_name.startswith("channel:"):
            assert isinstance(svc_status, str) and svc_status
            continue
        assert svc_status in allowed_statuses, (
            f"Unexpected status {svc_status!r} for service {svc_name!r}"
        )


def test_health_lists_all_services(client: TestClient) -> None:
    data = client.get("/health").json()
    expected = {"ollama", "redis", "postgres", "nats", "voice_sidecar", "status_line"}
    assert expected.issubset(set(data["services"].keys())), (
        f"Service list mismatch. Missing: {expected - set(data['services'].keys())}"
    )
    assert data["services"]["status_line"] == "ok"


def test_healthz_returns_lightweight_status(client: TestClient) -> None:
    data = client.get("/healthz").json()
    assert data == {"status": "healthy"}


def test_readyz_returns_runtime_dependency_status(client: TestClient) -> None:
    response = client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert set(data["services"]) == {"ollama", "openrouter", "postgres", "redis", "nats"}


def test_health_treats_inactive_openai_as_configured(
    client: TestClient,
    health_http_state: dict[str, object],
) -> None:
    response_codes = health_http_state["response_codes"]
    assert isinstance(response_codes, dict)
    response_codes["https://openrouter.ai/api/v1/models"] = 200
    response_codes[f"{settings.runtime_ollama_base_url}/api/version"] = 200
    response_codes["https://api.openai.com/v1/models"] = 401

    data = client.get("/health").json()

    assert data["status"] == "healthy"
    assert data["services"]["openai"] == "configured"
    assert "openai" not in data["required_services"]


def test_health_degrades_when_required_ollama_is_unavailable(
    client: TestClient,
    health_http_state: dict[str, object],
) -> None:
    response_codes = health_http_state["response_codes"]
    failures = health_http_state["failures"]
    assert isinstance(response_codes, dict)
    assert isinstance(failures, set)
    response_codes["https://openrouter.ai/api/v1/models"] = 200
    failures.add(f"{settings.runtime_ollama_base_url}/api/tags")

    data = client.get("/health").json()

    assert data["status"] == "degraded"
    assert data["required_services"]["ollama"] == "unavailable"


def test_health_degrades_when_required_embedding_model_is_missing(
    client: TestClient,
    health_http_state: dict[str, object],
) -> None:
    response_codes = health_http_state["response_codes"]
    response_payloads = health_http_state["response_payloads"]
    assert isinstance(response_codes, dict)
    assert isinstance(response_payloads, dict)
    response_codes["https://openrouter.ai/api/v1/models"] = 200
    response_payloads[f"{settings.runtime_ollama_base_url}/api/tags"] = {
        "models": [{"name": "qwen3-coder"}]
    }

    data = client.get("/health").json()

    assert data["status"] == "degraded"
    assert data["required_services"]["ollama"] == "degraded"


def test_default_provider_name_maps_claude_models_to_anthropic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health_routes, "resolve_default_model", lambda: "claude-3-5-sonnet")
    monkeypatch.setattr(health_routes, "llamacpp_enabled", lambda: False)

    assert health_routes._default_provider_name() == "anthropic"


def test_readyz_tracks_anthropic_runtime_dependencies(
    client: TestClient,
    health_http_state: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_codes = health_http_state["response_codes"]
    assert isinstance(response_codes, dict)
    monkeypatch.setattr(health_routes, "resolve_default_model", lambda: "claude-3-5-sonnet")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    response_codes["https://api.anthropic.com/v1/models"] = 200

    response = client.get("/readyz")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert set(data["services"]) == {"anthropic", "ollama", "postgres", "redis", "nats"}


def test_health_tracks_startup_runtime_when_using_ollama_engine(
    client: TestClient,
    health_http_state: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_codes = health_http_state["response_codes"]
    response_payloads = health_http_state["response_payloads"]
    assert isinstance(response_codes, dict)
    assert isinstance(response_payloads, dict)
    monkeypatch.setattr(settings, "local_orchestration_engine", "ollama")
    monkeypatch.setattr(settings, "local_orchestration_model", "qwen3-coder")
    response_codes["https://openrouter.ai/api/v1/models"] = 200
    response_payloads[f"{settings.runtime_ollama_base_url}/api/tags"] = {
        "models": [
            {"name": settings.embedding_default_model},
            {"name": "qwen3-coder:latest"},
        ]
    }

    data = client.get("/health").json()

    assert data["status"] == "healthy"
    assert data["required_services"]["local_orchestration"] == "ok"
    assert data["services"]["local_orchestration"] == "ok"
