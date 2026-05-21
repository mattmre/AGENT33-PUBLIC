"""Integration tests for application wiring (Phase 2).

Verifies that the FastAPI app starts/stops cleanly, middleware is applied,
and the lifespan initialises all expected connections (using mocks where
external services are unavailable).
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent33.tools.registry import ToolRegistry


def _make_mock_ltm():
    """Create a mock LongTermMemory instance."""
    m = MagicMock()
    m.initialize = AsyncMock()
    m.close = AsyncMock()
    m.scan = AsyncMock(return_value=[])
    return m


def _make_mock_nats_bus():
    """Create a mock NATSMessageBus instance."""
    m = MagicMock()
    m.connect = AsyncMock()
    m.close = AsyncMock()
    m.is_connected = False
    return m


def _make_mock_redis_module():
    """Create a mock redis.asyncio module with a mock client."""
    client = MagicMock()
    client.ping = AsyncMock(return_value=True)
    client.aclose = AsyncMock()
    mod = MagicMock()
    mod.from_url = MagicMock(return_value=client)
    return mod


@pytest.fixture
def patched_app():
    """Yield (app, TestClient) with all external I/O mocked."""
    from agent33.config import settings
    from agent33.main import app

    mock_ltm = _make_mock_ltm()
    mock_nats = _make_mock_nats_bus()
    mock_redis_mod = _make_mock_redis_module()
    missing_packs_dir = "__test_missing_packs__"

    with (
        patch("agent33.main.LongTermMemory", return_value=mock_ltm),
        patch("agent33.main.NATSMessageBus", return_value=mock_nats),
        patch.dict(sys.modules, {"redis": MagicMock(), "redis.asyncio": mock_redis_mod}),
        patch.object(settings, "pack_definitions_dir", missing_packs_dir),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        yield app, client, mock_ltm


@pytest.fixture
def ptc_patched_app():
    """Like patched_app but with ptc_enabled=True so PTC is registered during lifespan."""
    from agent33.config import settings
    from agent33.main import app

    mock_ltm = _make_mock_ltm()
    mock_nats = _make_mock_nats_bus()
    mock_redis_mod = _make_mock_redis_module()
    missing_packs_dir = "__test_missing_packs__"

    with (
        patch("agent33.main.LongTermMemory", return_value=mock_ltm),
        patch("agent33.main.NATSMessageBus", return_value=mock_nats),
        patch.dict(sys.modules, {"redis": MagicMock(), "redis.asyncio": mock_redis_mod}),
        patch.object(settings, "pack_definitions_dir", missing_packs_dir),
        patch.object(settings, "ptc_enabled", True),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        yield app, client, mock_ltm


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAppStartupShutdown:
    """Verify the app starts and stops without errors."""

    def test_app_starts_and_stops_cleanly(self, patched_app):
        """The app lifespan should complete startup and shutdown without raising.

        We verify startup occurred by checking that the DB mock was called and
        that app.state was populated (startup side-effects).
        """
        app, _client, mock_ltm = patched_app
        # If we get here, the lifespan started successfully
        mock_ltm.initialize.assert_awaited_once()
        assert hasattr(app.state, "long_term_memory")


class TestSecurityMiddleware:
    """Verify the AuthMiddleware is wired into the app."""

    def test_middleware_is_registered(self, patched_app):
        """The AuthMiddleware class should be present in the middleware stack."""
        from agent33.security.middleware import AuthMiddleware

        app, _, _ = patched_app
        middleware_classes = [getattr(m, "cls", None) for m in app.user_middleware]
        assert AuthMiddleware in middleware_classes

    def test_unauthenticated_request_returns_401(self, patched_app):
        """Non-public endpoints should require authentication."""
        _app, client, _ = patched_app
        resp = client.get("/agents/")
        assert resp.status_code == 401

    def test_cors_middleware_is_registered(self, patched_app):
        """CORSMiddleware should be present in the middleware stack."""
        from starlette.middleware.cors import CORSMiddleware

        app, _, _ = patched_app
        middleware_classes = [getattr(m, "cls", None) for m in app.user_middleware]
        assert CORSMiddleware in middleware_classes

    def test_preflight_options_not_rejected_by_auth(self, patched_app):
        """CORS preflight should not be blocked by auth middleware."""
        _app, client, _ = patched_app
        resp = client.options(
            "/v1/chat/completions",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert resp.status_code != 401
        assert "Missing authentication credentials" not in resp.text

    def test_dashboard_route_is_public_html(self, patched_app):
        """Dashboard page should render as public HTML."""
        _app, client, _ = patched_app
        resp = client.get("/v1/dashboard/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        assert "AGENT-33 Dashboard" in resp.text

    def test_benchmarks_router_is_mounted(self, patched_app):
        """Benchmarks router should be reachable through the main app."""
        _app, client, _ = patched_app
        resp = client.get(
            "/v1/benchmarks/skillsbench/runs",
            headers={"Authorization": "Bearer " + _make_test_token()},
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_mcp_proxy_router_is_mounted(self, patched_app):
        """MCP proxy router should be reachable through the main app."""
        _app, client, _ = patched_app
        resp = client.get(
            "/v1/mcp/proxy/health",
            headers={"Authorization": "Bearer " + _make_test_token()},
        )
        assert resp.status_code == 200
        assert "total" in resp.json()

    def test_mcp_sync_router_is_mounted(self, patched_app):
        """MCP sync router should be reachable through the main app."""
        _app, client, _ = patched_app
        resp = client.get(
            "/v1/mcp/sync/targets",
            headers={"Authorization": "Bearer " + _make_test_token()},
        )
        assert resp.status_code == 200
        assert "targets" in resp.json()


class TestLifespanState:
    """Verify that lifespan populates app.state with expected attributes."""

    def test_state_has_long_term_memory(self, patched_app):
        app, _, _ = patched_app
        assert hasattr(app.state, "long_term_memory")

    def test_state_has_nats_bus(self, patched_app):
        app, _, _ = patched_app
        assert hasattr(app.state, "nats_bus")

    def test_state_has_model_router(self, patched_app):
        app, _, _ = patched_app
        assert hasattr(app.state, "model_router")

    def test_state_has_redis(self, patched_app):
        app, _, _ = patched_app
        assert hasattr(app.state, "redis")

    def test_state_has_metrics_collector(self, patched_app):
        app, _, _ = patched_app
        assert hasattr(app.state, "metrics_collector")

    def test_state_has_alert_manager(self, patched_app):
        app, _, _ = patched_app
        assert hasattr(app.state, "alert_manager")

    def test_state_has_mcp_services(self, patched_app):
        app, _, _ = patched_app
        assert hasattr(app.state, "mcp_bridge")
        assert hasattr(app.state, "mcp_server")
        assert hasattr(app.state, "mcp_transport")
        assert hasattr(app.state, "proxy_manager")
        assert hasattr(app.state, "approval_token_manager")

    def test_state_has_tool_registry(self, patched_app):
        """Startup should populate the live shared tool registry."""
        app, _, _ = patched_app
        assert isinstance(app.state.tool_registry, ToolRegistry)

    def test_builtin_tools_are_registered_with_live_runtime_dependencies(self, patched_app):
        """Builtin tools should be registered against the startup runtime objects."""
        from agent33.config import settings
        from agent33.tools.builtin.browser import BrowserTool
        from agent33.tools.builtin.delegate_subtask import DelegateSubtaskTool
        from agent33.tools.builtin.ptc_execute import PTCExecuteTool

        app, _, _ = patched_app
        registry = app.state.tool_registry

        assert registry.get("apply_patch") is not None

        delegate_tool = registry.get("delegate_subtask")
        assert isinstance(delegate_tool, DelegateSubtaskTool)
        assert delegate_tool._router is app.state.model_router
        assert delegate_tool._tool_registry is registry

        browser_tool = registry.get("browser")
        assert isinstance(browser_tool, BrowserTool)
        assert browser_tool._router is app.state.model_router

        assert registry.get("web_search") is not None

        if settings.ptc_enabled:
            ptc_tool = registry.get("ptc_execute")
            assert isinstance(ptc_tool, PTCExecuteTool)
            assert ptc_tool._executor._tool_registry is registry


class TestPTCExecution:
    """Verify PTC tool wired through lifespan can actually execute code."""

    def test_ptc_execute_tool_runs_safe_expression_via_lifespan(self, ptc_patched_app):
        """PTCExecuteTool wired through lifespan should execute safe code.

        This goes beyond registration: it calls execute() with a real Python
        expression and asserts the subprocess produced the expected output.
        The fixture forces ptc_enabled=True so the test never skips in CI.
        """
        import asyncio

        from agent33.tools.base import ToolContext
        from agent33.tools.builtin.ptc_execute import PTCExecuteTool

        app, _, _ = ptc_patched_app

        ptc_tool = app.state.tool_registry.get("ptc_execute")
        assert isinstance(ptc_tool, PTCExecuteTool)

        ctx = ToolContext(tenant_id="test-tenant")
        result = asyncio.run(ptc_tool.execute({"code": "print(1 + 1)"}, ctx))
        assert result.success is True
        assert "2" in result.output


class TestEmbeddingSubsystem:
    """Verify embedding provider, cache, and RAG wiring."""

    def test_state_has_embedding_provider(self, patched_app):
        app, _, _ = patched_app
        assert hasattr(app.state, "embedding_provider")
        from agent33.memory.embeddings import EmbeddingProvider

        assert isinstance(app.state.embedding_provider, EmbeddingProvider)

    def test_state_has_embedding_cache_when_enabled(self, patched_app):
        """When embedding_cache_enabled (default True), cache should be on state."""
        app, _, _ = patched_app
        from agent33.config import settings

        if settings.embedding_cache_enabled:
            assert hasattr(app.state, "embedding_cache")
            from agent33.memory.cache import EmbeddingCache

            assert isinstance(app.state.embedding_cache, EmbeddingCache)

    def test_state_has_bm25_index(self, patched_app):
        app, _, _ = patched_app
        from agent33.memory.bm25 import BM25Index

        assert isinstance(app.state.bm25_index, BM25Index)
        assert app.state.bm25_index.size == 0  # starts empty

    def test_state_has_rag_pipeline(self, patched_app):
        app, _, _ = patched_app
        from agent33.memory.rag import RAGPipeline

        assert isinstance(app.state.rag_pipeline, RAGPipeline)

    def test_state_has_hybrid_searcher_when_enabled(self, patched_app):
        app, _, _ = patched_app
        from agent33.config import settings

        if settings.rag_hybrid_enabled:
            assert hasattr(app.state, "hybrid_searcher")
            from agent33.memory.hybrid import HybridSearcher

            assert isinstance(app.state.hybrid_searcher, HybridSearcher)

    def test_state_has_progressive_recall(self, patched_app):
        app, _, _ = patched_app
        from agent33.memory.progressive_recall import ProgressiveRecall

        assert isinstance(app.state.progressive_recall, ProgressiveRecall)


class TestSkillSubsystem:
    """Verify skill registry and injector wiring."""

    def test_state_has_skill_registry(self, patched_app):
        app, _, _ = patched_app
        from agent33.skills.registry import SkillRegistry

        assert isinstance(app.state.skill_registry, SkillRegistry)

    def test_state_has_skill_injector(self, patched_app):
        app, _, _ = patched_app
        from agent33.skills.injection import SkillInjector

        assert isinstance(app.state.skill_injector, SkillInjector)

    def test_skill_registry_loads_imported_pack_skills_when_no_standalone_dir(self, patched_app):
        """Standalone-skill absence should not block imported pack skills from loading."""
        app, _, _ = patched_app

        pack_count = app.state.pack_registry.count
        loaded_names = {skill.name for skill in app.state.skill_registry.list_all()}
        expected_pack_skills = {
            "workflow-ops/pr-manager",
            "workflow-ops/planning-with-files",
            "platform-builder/mcp-builder",
        }

        # Default skill_definitions_dir = "skills" still doesn't exist in this test env.
        # When pack_definitions_dir resolves to shipped capability packs, those pack skills
        # should populate the registry; otherwise they should be absent. Runtime-ingested
        # skills may still be hydrated by earlier lifecycle tests in the same suite.
        if pack_count == 0:
            assert loaded_names.isdisjoint(expected_pack_skills)
            return

        assert expected_pack_skills.issubset(loaded_names)
        assert pack_count >= 3

    def test_promoted_skill_asset_is_discoverable_through_runtime_registries(self, patched_app):
        """Publishing a skill asset should update the shared runtime registries."""
        app, client, _ = patched_app

        create = client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "runtime-ingested-skill",
                "asset_type": "skill",
                "source_uri": None,
                "tenant_id": "tenant-runtime-skill",
                "metadata": {
                    "skill_definition": {
                        "name": "runtime-ingested-skill",
                        "description": "Published via ingestion.",
                        "instructions": "Use the published skill.",
                    }
                },
            },
            headers={"Authorization": "Bearer " + _make_test_token()},
        )
        assert create.status_code == 201
        asset_id = create.json()["id"]

        validate = client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated", "operator": "tester"},
            headers={"Authorization": "Bearer " + _make_test_token()},
        )
        assert validate.status_code == 200

        publish = client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "published", "operator": "tester"},
            headers={"Authorization": "Bearer " + _make_test_token()},
        )
        assert publish.status_code == 200

        registered = app.state.skill_registry.get("runtime-ingested-skill")
        assert registered is not None
        assert registered.description == "Published via ingestion."
        assert app.state.command_registry.get_command_info("/runtime-ingested-skill") is not None


class TestAgentWorkflowBridge:
    """Verify the agent runtime bridge is registered in invoke_agent registry."""

    def test_default_agent_registered(self, patched_app):
        from agent33.workflows.actions.invoke_agent import get_agent

        _app, _, _ = patched_app
        handler = get_agent("__default__")
        assert callable(handler)


class TestAgentInvokeSubsystemPassthrough:
    """Verify the invoke endpoint passes subsystems to AgentRuntime."""

    def test_invoke_route_passes_skill_injector(self, patched_app):
        """The invoke route should pull skill_injector from app.state."""
        from unittest.mock import patch as mock_patch

        from agent33.agents.definition import (
            AgentConstraints,
            AgentDefinition,
            AgentParameter,
            AgentRole,
        )
        from agent33.agents.runtime import AgentResult

        app, client, _ = patched_app

        # Register a dummy agent
        dummy_def = AgentDefinition(
            name="test-agent",
            version="1.0.0",
            role=AgentRole.WORKER,
            description="test",
            inputs={"prompt": AgentParameter(type="string", description="input")},
            outputs={"result": AgentParameter(type="string", description="output")},
            constraints=AgentConstraints(),
        )
        app.state.agent_registry.register(dummy_def)

        mock_result = AgentResult(
            output={"result": "ok"},
            raw_response='{"result":"ok"}',
            tokens_used=10,
            model="test",
        )

        with mock_patch(
            "agent33.api.routes.agents.AgentRuntime",
            autospec=True,
        ) as mock_runtime_cls:
            mock_instance = MagicMock()
            mock_instance.invoke = AsyncMock(return_value=mock_result)
            mock_runtime_cls.return_value = mock_instance

            resp = client.post(
                "/v1/agents/test-agent/invoke",
                json={"inputs": {"prompt": "hello"}},
                headers={"Authorization": "Bearer " + _make_test_token()},
            )

            assert resp.status_code == 200
            # Verify subsystems were passed to AgentRuntime constructor
            call_kwargs = mock_runtime_cls.call_args.kwargs
            assert "skill_injector" in call_kwargs
            assert "progressive_recall" in call_kwargs
            assert "active_skills" in call_kwargs
            assert call_kwargs["skill_injector"] is app.state.skill_injector
            assert call_kwargs["progressive_recall"] is app.state.progressive_recall
            assert call_kwargs["active_skills"] == []

    def test_invoke_route_uses_skill_matcher_when_feature_flag_enabled(self, patched_app):
        """When enabled, skill matcher output should drive runtime active_skills."""
        from unittest.mock import patch as mock_patch

        from agent33.agents.definition import (
            AgentConstraints,
            AgentDefinition,
            AgentParameter,
            AgentRole,
        )
        from agent33.agents.runtime import AgentResult
        from agent33.config import settings

        app, client, _ = patched_app
        dummy_def = AgentDefinition(
            name="skill-agent",
            version="1.0.0",
            role=AgentRole.WORKER,
            description="test matcher",
            skills=["skill-a", "skill-b"],
            inputs={"prompt": AgentParameter(type="string", description="input")},
            outputs={"result": AgentParameter(type="string", description="output")},
            constraints=AgentConstraints(),
        )
        app.state.agent_registry.register(dummy_def)

        mock_result = AgentResult(
            output={"result": "ok"},
            raw_response='{"result":"ok"}',
            tokens_used=10,
            model="test",
        )
        skill_ok = type("MatchedSkill", (), {"name": "skill-b"})()
        skill_other = type("MatchedSkill", (), {"name": "not-allowed"})()
        mock_matcher = MagicMock()
        mock_matcher.match = AsyncMock(return_value=MagicMock(skills=[skill_ok, skill_other]))
        app.state.skill_matcher = mock_matcher

        original = settings.skillsbench_skill_matcher_enabled
        settings.skillsbench_skill_matcher_enabled = True
        try:
            with mock_patch(
                "agent33.api.routes.agents.AgentRuntime",
                autospec=True,
            ) as mock_runtime_cls:
                mock_instance = MagicMock()
                mock_instance.invoke = AsyncMock(return_value=mock_result)
                mock_runtime_cls.return_value = mock_instance

                resp = client.post(
                    "/v1/agents/skill-agent/invoke",
                    json={"inputs": {"prompt": "hello"}},
                    headers={"Authorization": "Bearer " + _make_test_token()},
                )
                assert resp.status_code == 200
                call_kwargs = mock_runtime_cls.call_args.kwargs
                assert call_kwargs["active_skills"] == ["skill-b"]
                mock_matcher.match.assert_awaited_once()
        finally:
            settings.skillsbench_skill_matcher_enabled = original


def _make_test_token() -> str:
    """Create a valid JWT for testing."""
    import jwt

    from agent33.config import settings

    return jwt.encode(
        {"sub": "test-user", "scopes": ["admin"]},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
