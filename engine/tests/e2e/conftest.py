"""Shared fixtures for E2E integration tests.

These fixtures create a FastAPI app with all external I/O mocked (PostgreSQL,
Redis, NATS, LLM providers) but internal subsystem wiring kept intact.  Tests
exercise real cross-subsystem flows through the HTTP API layer.
"""

from __future__ import annotations

import hashlib
import math
import sys
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent33.security.auth import create_access_token

if TYPE_CHECKING:
    from httpx import Response

# ---------------------------------------------------------------------------
# Deterministic embedding function (bag-of-words hash, no model needed)
# ---------------------------------------------------------------------------

_EMBED_DIM = 384


def _deterministic_embed(text: str) -> list[float]:
    """Produce a deterministic embedding from text via hashed character n-grams.

    This gives semantically-related strings similar vectors (shared n-grams)
    while keeping unrelated strings orthogonal.
    """
    vec = [0.0] * _EMBED_DIM
    words = text.lower().split()
    for w in words:
        idx = int(hashlib.sha256(w.encode()).hexdigest(), 16) % _EMBED_DIM
        vec[idx] += 1.0
    # L2-normalise
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _make_mock_ltm() -> MagicMock:
    """Create a mock LongTermMemory instance."""
    m = MagicMock()
    m.initialize = AsyncMock()
    m.close = AsyncMock()
    m.store = AsyncMock(return_value="e2e-memory-record")
    m.search = AsyncMock(return_value=[])
    return m


def _make_mock_nats_bus() -> MagicMock:
    """Create a mock NATSMessageBus instance."""
    m = MagicMock()
    m.connect = AsyncMock()
    m.close = AsyncMock()
    m.is_connected = False
    return m


def _make_mock_redis_module() -> MagicMock:
    """Create a mock redis.asyncio module with a mock client."""
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)
    client.aclose = AsyncMock()
    mod = MagicMock()
    mod.from_url = MagicMock(return_value=client)
    return mod


def _make_embedding_provider() -> AsyncMock:
    """Create a deterministic embedding provider for E2E harness tests."""
    provider = AsyncMock()
    provider.embed = AsyncMock(side_effect=lambda text: _deterministic_embed(text))
    provider.embed_batch = AsyncMock(
        side_effect=lambda texts: [_deterministic_embed(text) for text in texts]
    )
    provider.close = AsyncMock()
    return provider


class _AuthClientProxy:
    """Lightweight auth wrapper that avoids starting nested TestClient instances."""

    def __init__(self, client: TestClient, headers: dict[str, str]) -> None:
        self._client = client
        self._headers = headers

    def _merged_headers(self, extra_headers: dict[str, str] | None) -> dict[str, str]:
        headers = dict(self._headers)
        if extra_headers is None:
            return headers

        header_keys = {key.lower(): key for key in headers}
        for key, value in extra_headers.items():
            existing_key = header_keys.get(key.lower())
            if existing_key is not None:
                headers.pop(existing_key, None)
            headers[key] = value
            header_keys[key.lower()] = key
        return headers

    def request(self, method: str, url: str, **kwargs: Any) -> Response:
        headers = self._merged_headers(kwargs.pop("headers", None))
        return self._client.request(method, url, headers=headers, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Response:
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> Response:
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> Response:
        return self.request("DELETE", url, **kwargs)


# ---------------------------------------------------------------------------
# Core E2E app fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def e2e_app():
    """Create a FastAPI app with all external deps mocked but internal wiring intact.

    Yields (app, mock_ltm) so tests can inspect app.state and the LTM mock.
    The app goes through the real lifespan, initializing AgentRegistry,
    ModelRouter, EmbeddingProvider, SkillRegistry, HookRegistry, etc.
    """
    from agent33.main import app

    mock_ltm = _make_mock_ltm()
    mock_nats = _make_mock_nats_bus()
    mock_redis_mod = _make_mock_redis_module()
    mock_embedding_provider = _make_embedding_provider()

    with (
        patch("agent33.main.LongTermMemory", return_value=mock_ltm),
        patch("agent33.main.NATSMessageBus", return_value=mock_nats),
        patch("agent33.memory.embeddings.EmbeddingProvider", return_value=mock_embedding_provider),
        patch.dict(sys.modules, {"redis": MagicMock(), "redis.asyncio": mock_redis_mod}),
    ):
        app.state._e2e_embedding_provider = mock_embedding_provider
        yield app, mock_ltm


@pytest.fixture
def e2e_client(e2e_app):
    """TestClient against the E2E app, not authenticated.

    Yields (app, client, mock_ltm).
    """
    app, mock_ltm = e2e_app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield app, client, mock_ltm


# ---------------------------------------------------------------------------
# Authenticated client fixtures
# ---------------------------------------------------------------------------


def _make_token(
    subject: str = "test-user",
    scopes: list[str] | None = None,
    tenant_id: str = "",
) -> str:
    """Create a valid JWT for testing."""
    return create_access_token(
        subject,
        scopes=scopes or ["admin"],
        tenant_id=tenant_id,
    )


@pytest.fixture
def admin_token() -> str:
    """JWT with admin scopes (no tenant binding -- sees everything)."""
    return _make_token(subject="admin-user", scopes=["admin"])


@pytest.fixture
def tenant_a_token() -> str:
    """JWT bound to tenant-a."""
    return _make_token(
        subject="user-a",
        scopes=[
            "agents:read",
            "agents:write",
            "agents:invoke",
            "workflows:read",
            "workflows:write",
            "workflows:execute",
            "sessions:read",
            "sessions:write",
            "hooks:read",
            "hooks:manage",
        ],
        tenant_id="tenant-a",
    )


@pytest.fixture
def tenant_b_token() -> str:
    """JWT bound to tenant-b."""
    return _make_token(
        subject="user-b",
        scopes=[
            "agents:read",
            "agents:write",
            "agents:invoke",
            "workflows:read",
            "workflows:write",
            "workflows:execute",
            "sessions:read",
            "sessions:write",
            "hooks:read",
            "hooks:manage",
        ],
        tenant_id="tenant-b",
    )


@pytest.fixture
def admin_client(e2e_client, admin_token):
    """TestClient authenticated as admin (no tenant filter)."""
    app, client, mock_ltm = e2e_client
    return app, _AuthClientProxy(client, {"Authorization": f"Bearer {admin_token}"}), mock_ltm


@pytest.fixture
def tenant_a_client(e2e_client, tenant_a_token):
    """TestClient authenticated as tenant-a."""
    app, base_client, mock_ltm = e2e_client
    yield app, _AuthClientProxy(base_client, {"Authorization": f"Bearer {tenant_a_token}"})


@pytest.fixture
def tenant_b_client(e2e_client, tenant_b_token):
    """TestClient authenticated as tenant-b."""
    app, base_client, mock_ltm = e2e_client
    yield app, _AuthClientProxy(base_client, {"Authorization": f"Bearer {tenant_b_token}"})


# ---------------------------------------------------------------------------
# Agent definition helpers
# ---------------------------------------------------------------------------

_SAMPLE_AGENT_DEF = {
    "name": "e2e-test-agent",
    "version": "1.0.0",
    "role": "worker",
    "description": "Agent for E2E testing",
    "inputs": {"prompt": {"type": "string", "description": "User prompt"}},
    "outputs": {"result": {"type": "string", "description": "Agent output"}},
    "constraints": {
        "max_tokens": 256,
        "timeout_seconds": 10,
        "max_retries": 0,
    },
}


@pytest.fixture
def sample_agent_def() -> dict[str, Any]:
    """Return a minimal agent definition dict for E2E tests."""
    return dict(_SAMPLE_AGENT_DEF)


@pytest.fixture
def sample_workflow_def() -> dict[str, Any]:
    """Return a minimal two-step sequential workflow definition."""
    return {
        "name": "e2e-test-workflow",
        "version": "1.0.0",
        "description": "E2E test workflow",
        "steps": [
            {
                "id": "step-1",
                "action": "transform",
                "config": {"expression": "'Hello ' + inputs.get('name', 'World')"},
            },
            {
                "id": "step-2",
                "action": "transform",
                "config": {"expression": "state.get('step-1', {}).get('result', '') + '!'"},
                "depends_on": ["step-1"],
            },
        ],
    }
