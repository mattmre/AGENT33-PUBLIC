"""Comprehensive tests for operator control plane API endpoints.

Tests cover:
- GET /v1/operator/status  -- system status with inventory counts
- GET /v1/operator/config  -- redacted config
- GET /v1/operator/doctor  -- diagnostic checks
- POST /v1/operator/reset  -- cache/registry reset
- GET /v1/operator/tools/summary -- tool listing
- GET /v1/operator/sessions -- session catalog
- GET /v1/operator/backups  -- delegated backup catalog response
- Auth enforcement (401/403) on all endpoints
"""

from __future__ import annotations

import contextlib
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.operator.service import OperatorService
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def operator_read_client() -> TestClient:
    """Client with operator:read scope."""
    token = create_access_token("op-reader", scopes=["operator:read"], tenant_id="test-tenant")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def operator_write_client() -> TestClient:
    """Client with operator:read + operator:write scopes."""
    token = create_access_token(
        "op-writer",
        scopes=["operator:read", "operator:write"],
        tenant_id="test-tenant",
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def admin_client() -> TestClient:
    """Client with admin scope."""
    token = create_access_token("admin-user", scopes=["admin"], tenant_id="test-tenant")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def no_auth_client() -> TestClient:
    """Client with no auth headers."""
    return TestClient(app)


@pytest.fixture()
def wrong_scope_client() -> TestClient:
    """Client with unrelated scopes (no operator access)."""
    token = create_access_token("chat-user", scopes=["agents:read"], tenant_id="test-tenant")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


class FakeAgentRegistry:
    """Minimal agent registry mock."""

    def __init__(self, agents: list[Any] | None = None) -> None:
        self._agents = agents or []

    def list_all(self) -> list[Any]:
        return self._agents

    def get(self, name: str) -> Any:
        return None

    def discover(self, path: Any) -> int:
        return len(self._agents)


class FakeToolRegistry:
    """Minimal tool registry mock."""

    def __init__(self, tools: list[Any] | None = None) -> None:
        self._tools = tools or []

    def list_all(self) -> list[Any]:
        return self._tools

    def get_entry(self, name: str) -> Any:
        return None


class FakePluginRegistry:
    """Minimal plugin registry mock."""

    def __init__(self, plugins: list[Any] | None = None) -> None:
        self._plugins = plugins or []

    def list_all(self) -> list[Any]:
        return self._plugins

    def get_state(self, name: str) -> Any:
        return SimpleNamespace(value="active")

    @property
    def count(self) -> int:
        return len(self._plugins)


class FakePackRegistry:
    """Minimal pack registry mock."""

    def __init__(self, packs: list[Any] | None = None) -> None:
        self._packs = packs or []

    def list_all(self) -> list[Any]:
        return self._packs

    def discover(self) -> int:
        return len(self._packs)


class FakeSkillRegistry:
    """Minimal skill registry mock."""

    def __init__(self, skills: list[Any] | None = None) -> None:
        self._skills = skills or []

    def list_all(self) -> list[Any]:
        return self._skills


class FakeHookRegistry:
    """Minimal hook registry mock."""

    def __init__(self, hook_count: int = 0) -> None:
        self._count = hook_count

    def count(self) -> int:
        return self._count


class FakeNATSBus:
    """Minimal NATS bus mock."""

    def __init__(self, connected: bool = True) -> None:
        self.is_connected = connected


class FakeAsyncHealthService:
    """Minimal async health snapshot mock."""

    def __init__(self, status: str = "ok") -> None:
        self._status = status

    async def health_snapshot(self) -> dict[str, str]:
        return {"status": self._status}


def _make_operator_service(
    *,
    agent_count: int = 3,
    tool_count: int = 5,
    plugin_count: int = 2,
    pack_count: int = 1,
    skill_count: int = 4,
    hook_count: int = 7,
    redis_available: bool = True,
    nats_connected: bool = True,
) -> OperatorService:
    """Build an OperatorService with fake registries."""
    from agent33.config import Settings

    fake_agents = [SimpleNamespace(name=f"agent-{i}") for i in range(agent_count)]
    fake_tools = [
        SimpleNamespace(name=f"tool-{i}", parameters_schema=None) for i in range(tool_count)
    ]
    fake_plugins = [SimpleNamespace(name=f"plugin-{i}") for i in range(plugin_count)]
    fake_packs = [SimpleNamespace(name=f"pack-{i}") for i in range(pack_count)]
    fake_skills = [SimpleNamespace(name=f"skill-{i}") for i in range(skill_count)]

    state = SimpleNamespace(
        agent_registry=FakeAgentRegistry(fake_agents),
        tool_registry=FakeToolRegistry(fake_tools),
        plugin_registry=FakePluginRegistry(fake_plugins),
        pack_registry=FakePackRegistry(fake_packs),
        skill_registry=FakeSkillRegistry(fake_skills),
        hook_registry=FakeHookRegistry(hook_count),
        redis=MagicMock() if redis_available else None,
        nats_bus=FakeNATSBus(nats_connected),
        long_term_memory=MagicMock(),
        multimodal_service=SimpleNamespace(
            list_voice_sessions=lambda limit=1000: [
                SimpleNamespace(state=SimpleNamespace(value="active"))
            ]
        ),
        voice_sidecar_probe=FakeAsyncHealthService("ok"),
        status_line_service=FakeAsyncHealthService("ok"),
    )

    settings = Settings(_env_file=None)

    return OperatorService(
        app_state=state,
        settings=settings,
        start_time=time.time() - 3600,  # 1 hour ago
    )


@pytest.fixture(autouse=True)
def _install_operator_service() -> Any:
    """Install a mocked OperatorService on app.state for all tests."""
    svc = _make_operator_service()
    original = getattr(app.state, "operator_service", None)
    app.state.operator_service = svc
    yield svc
    if original is not None:
        app.state.operator_service = original
    else:
        # Remove the attribute to restore pre-test state
        with contextlib.suppress(AttributeError):
            del app.state.operator_service


# ============================================================================
# Auth enforcement tests
# ============================================================================


class TestOperatorAuth:
    """Verify 401 (no token) and 403 (wrong scope) on all operator endpoints."""

    READ_ENDPOINTS = [
        "/v1/operator/status",
        "/v1/operator/config",
        "/v1/operator/doctor",
        "/v1/operator/tools/summary",
        "/v1/operator/sessions",
        "/v1/operator/backups",
    ]

    def test_no_auth_returns_401(self, no_auth_client: TestClient) -> None:
        for path in self.READ_ENDPOINTS:
            resp = no_auth_client.get(path)
            assert resp.status_code == 401, f"Expected 401 for {path}, got {resp.status_code}"

    def test_no_auth_reset_returns_401(self, no_auth_client: TestClient) -> None:
        resp = no_auth_client.post("/v1/operator/reset", json={"targets": ["all"]})
        assert resp.status_code == 401

    def test_wrong_scope_returns_403(self, wrong_scope_client: TestClient) -> None:
        for path in self.READ_ENDPOINTS:
            resp = wrong_scope_client.get(path)
            assert resp.status_code == 403, f"Expected 403 for {path}, got {resp.status_code}"

    def test_wrong_scope_reset_returns_403(self, wrong_scope_client: TestClient) -> None:
        resp = wrong_scope_client.post("/v1/operator/reset", json={"targets": ["all"]})
        assert resp.status_code == 403

    def test_read_scope_cannot_reset(self, operator_read_client: TestClient) -> None:
        """operator:read cannot POST /reset (requires operator:write)."""
        resp = operator_read_client.post("/v1/operator/reset", json={"targets": ["all"]})
        assert resp.status_code == 403

    def test_admin_scope_grants_access(self, admin_client: TestClient) -> None:
        """Admin scope should grant access to all operator endpoints."""
        for path in self.READ_ENDPOINTS:
            resp = admin_client.get(path)
            assert resp.status_code == 200, f"Expected 200 for {path}, got {resp.status_code}"


# ============================================================================
# GET /v1/operator/status
# ============================================================================


class TestOperatorStatus:
    """Test the status endpoint returns correct structure and inventory counts."""

    def test_returns_health_services(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "health" in data
        assert "status" in data["health"]
        assert "services" in data["health"]
        assert data["health"]["services"]["voice_sidecar"] == "ok"
        assert data["health"]["services"]["status_line"] == "ok"

    def test_returns_inventories(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/status")
        data = resp.json()
        inv = data["inventories"]
        assert inv["agents"]["count"] == 3
        assert inv["agents"]["loaded"] is True
        assert inv["tools"]["count"] == 5
        assert inv["plugins"]["count"] == 2
        assert inv["plugins"]["active"] == 2
        assert inv["packs"]["count"] == 1
        assert inv["skills"]["count"] == 4
        assert inv["hooks"]["count"] == 7
        assert inv["voice_sessions"]["active"] == 1

    def test_returns_runtime_info(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/status")
        data = resp.json()
        runtime = data["runtime"]
        assert runtime["version"] == "0.1.0"
        assert "python_version" in runtime
        assert runtime["uptime_seconds"] > 0
        assert runtime["start_time"] is not None

    def test_returns_pending_items(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/status")
        data = resp.json()
        pending = data["pending"]
        assert "approvals" in pending
        assert "reviews" in pending
        assert "improvements" in pending

    def test_degraded_when_redis_unavailable(self, operator_read_client: TestClient) -> None:
        svc = _make_operator_service(redis_available=False)
        app.state.operator_service = svc
        resp = operator_read_client.get("/v1/operator/status")
        data = resp.json()
        assert data["health"]["status"] == "degraded"
        assert data["health"]["services"]["redis"] == "unavailable"

    def test_degraded_when_nats_disconnected(self, operator_read_client: TestClient) -> None:
        svc = _make_operator_service(nats_connected=False)
        app.state.operator_service = svc
        resp = operator_read_client.get("/v1/operator/status")
        data = resp.json()
        assert data["health"]["status"] == "degraded"
        assert data["health"]["services"]["nats"] == "unavailable"


# ============================================================================
# GET /v1/operator/config
# ============================================================================


class TestOperatorConfig:
    """Test config endpoint returns grouped config with redacted secrets."""

    def test_returns_groups(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "groups" in data
        assert "feature_flags" in data
        assert "database" in data["groups"]
        assert "redis" in data["groups"]
        assert "security" in data["groups"]

    def test_secrets_are_redacted(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/config")
        data = resp.json()
        security = data["groups"]["security"]
        assert security["jwt_secret"] == "***"
        assert security["api_secret_key"] == "***"

    def test_database_url_is_masked(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/config")
        data = resp.json()
        db_url = data["groups"]["database"]["database_url"]
        # Should not contain raw credentials
        assert "agent33:agent33@" not in db_url
        assert "***:***@" in db_url

    def test_feature_flags_present(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/config")
        data = resp.json()
        flags = data["feature_flags"]
        assert "hooks_enabled" in flags
        assert "training_enabled" in flags
        assert "embedding_cache_enabled" in flags
        assert isinstance(flags["hooks_enabled"], bool)

    def test_encryption_key_empty_shows_empty(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/config")
        data = resp.json()
        # Default encryption_key is empty string, so redact returns ""
        assert data["groups"]["security"]["encryption_key"] == ""

    def test_openrouter_key_presence_is_redacted(self, operator_read_client: TestClient) -> None:
        from pydantic import SecretStr

        svc = _make_operator_service()
        object.__setattr__(svc._settings, "openai_api_key", SecretStr("sk-openai-test"))
        object.__setattr__(svc._settings, "openrouter_api_key", SecretStr("sk-or-test"))
        app.state.operator_service = svc
        resp = operator_read_client.get("/v1/operator/config")
        data = resp.json()
        assert data["groups"]["llm"]["openai_api_key"] == "***"
        assert data["groups"]["llm"]["openrouter_api_key"] == "***"

    def test_default_model_is_exposed_via_llm_group(
        self, operator_read_client: TestClient
    ) -> None:
        svc = _make_operator_service()
        object.__setattr__(svc._settings, "default_model", "openrouter/auto")
        app.state.operator_service = svc
        resp = operator_read_client.get("/v1/operator/config")
        data = resp.json()
        assert data["groups"]["llm"]["default_model"] == "openrouter/auto"
        assert "default_model" not in data["groups"]["ollama"]

    def test_local_orchestration_config_is_exposed(self, operator_read_client: TestClient) -> None:
        svc = _make_operator_service()
        object.__setattr__(
            svc._settings, "local_orchestration_base_url", "http://localhost:8033/v1"
        )
        object.__setattr__(svc._settings, "local_orchestration_model", "qwen3-coder-next")
        object.__setattr__(svc._settings, "local_orchestration_engine", "vLLM")
        app.state.operator_service = svc

        resp = operator_read_client.get("/v1/operator/config")

        data = resp.json()
        lo = data["groups"]["local_orchestration"]
        assert lo["local_orchestration_base_url"] == "http://localhost:8033/v1"
        assert lo["local_orchestration_model"] == "qwen3-coder-next"
        assert lo["local_orchestration_engine"] == "vLLM"


# ============================================================================
# GET /v1/operator/doctor
# ============================================================================


class TestOperatorDoctor:
    """Test diagnostics endpoint runs checks and returns structured results."""

    def test_returns_checks_list(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/doctor")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall" in data
        assert "checks" in data
        assert "timestamp" in data
        assert isinstance(data["checks"], list)
        assert len(data["checks"]) > 0

    def test_each_check_has_required_fields(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/doctor")
        data = resp.json()
        for check in data["checks"]:
            assert "id" in check
            assert "category" in check
            assert "status" in check
            assert "message" in check
            assert check["status"] in {"ok", "warning", "error"}

    def test_security_check_warns_on_defaults(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/doctor")
        data = resp.json()
        sec_checks = [c for c in data["checks"] if c["id"] == "DOC-09"]
        assert len(sec_checks) == 1
        sec = sec_checks[0]
        # In dev/test mode, jwt_secret is auto-generated (P62), so DOC-09 warns about
        # database credentials and/or API secret key, but NOT the JWT secret.
        assert sec["status"] == "warning"
        assert "JWT secret" not in sec["message"]
        # Database URL and/or API secret key should still be flagged
        assert sec["message"] != ""
        assert sec["remediation"] is not None

    def test_overall_reflects_worst_status(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/doctor")
        data = resp.json()
        statuses = {c["status"] for c in data["checks"]}
        if "error" in statuses:
            assert data["overall"] == "error"
        elif "warning" in statuses:
            assert data["overall"] == "warning"
        else:
            assert data["overall"] == "ok"

    def test_check_ids_are_unique(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/doctor")
        data = resp.json()
        ids = [c["id"] for c in data["checks"]]
        assert len(ids) == len(set(ids)), f"Duplicate check IDs: {ids}"


# ============================================================================
# POST /v1/operator/reset
# ============================================================================


class TestOperatorReset:
    """Test the reset endpoint clears caches and re-discovers registries."""

    def test_reset_all_returns_actions(self, operator_write_client: TestClient) -> None:
        resp = operator_write_client.post("/v1/operator/reset", json={"targets": ["all"]})
        assert resp.status_code == 200
        data = resp.json()
        assert "actions" in data
        assert "timestamp" in data
        assert isinstance(data["actions"], list)
        assert len(data["actions"]) > 0

    def test_reset_caches_only(self, operator_write_client: TestClient) -> None:
        resp = operator_write_client.post("/v1/operator/reset", json={"targets": ["caches"]})
        assert resp.status_code == 200
        data = resp.json()
        targets = {a["target"] for a in data["actions"]}
        assert "embedding_cache" in targets
        assert "bm25_index" in targets
        # Should NOT contain registry targets
        assert "agent_registry" not in targets

    def test_reset_registries_only(self, operator_write_client: TestClient) -> None:
        resp = operator_write_client.post("/v1/operator/reset", json={"targets": ["registries"]})
        assert resp.status_code == 200
        data = resp.json()
        targets = {a["target"] for a in data["actions"]}
        # Should contain registry rediscovery targets
        assert "agent_registry" in targets
        # Should NOT contain cache targets
        assert "embedding_cache" not in targets

    def test_reset_actions_report_success(self, operator_write_client: TestClient) -> None:
        resp = operator_write_client.post("/v1/operator/reset", json={"targets": ["all"]})
        data = resp.json()
        for action in data["actions"]:
            assert "success" in action
            assert "detail" in action
            assert isinstance(action["success"], bool)

    def test_default_target_is_all(self, operator_write_client: TestClient) -> None:
        resp = operator_write_client.post("/v1/operator/reset", json={})
        assert resp.status_code == 200
        data = resp.json()
        targets = {a["target"] for a in data["actions"]}
        # Should have both cache and registry actions
        assert "embedding_cache" in targets
        assert "agent_registry" in targets


# ============================================================================
# GET /v1/operator/tools/summary
# ============================================================================


class TestOperatorToolsSummary:
    """Test the tools summary endpoint lists tools correctly."""

    def test_returns_tool_list(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/tools/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert "count" in data
        assert data["count"] == 5

    def test_tool_items_have_required_fields(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/tools/summary")
        data = resp.json()
        for tool in data["tools"]:
            assert "name" in tool
            assert "source" in tool
            assert "status" in tool
            assert "has_schema" in tool

    def test_includes_phase2_note(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/tools/summary")
        data = resp.json()
        assert "note" in data
        assert "Phase 2" in data["note"]

    def test_empty_when_no_tool_registry(self, operator_read_client: TestClient) -> None:
        svc = _make_operator_service(tool_count=0)
        app.state.operator_service = svc
        resp = operator_read_client.get("/v1/operator/tools/summary")
        data = resp.json()
        assert data["count"] == 0
        assert data["tools"] == []


# ============================================================================
# GET /v1/operator/sessions
# ============================================================================


class TestOperatorSessions:
    """Test the session catalog endpoint."""

    def test_returns_session_list(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert "count" in data
        assert "total" in data
        assert isinstance(data["sessions"], list)

    def test_degraded_when_no_redis(self, operator_read_client: TestClient) -> None:
        svc = _make_operator_service(redis_available=False)
        app.state.operator_service = svc
        resp = operator_read_client.get("/v1/operator/sessions")
        data = resp.json()
        assert data["degraded"] is True


# ============================================================================
# GET /v1/operator/backups
# ============================================================================


class TestOperatorBackups:
    """Test the delegated backup catalog endpoint."""

    def test_returns_delegated_catalog_response(self, operator_read_client: TestClient) -> None:
        resp = operator_read_client.get("/v1/operator/backups")
        assert resp.status_code == 200
        data = resp.json()
        assert "backups" in data
        assert data["backups"] == []
        assert data["count"] == 0
        assert data["note"] == "Platform backup inventory is available under /v1/backups"
