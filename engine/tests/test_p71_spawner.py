"""Tests for Phase 71: Sub-Agent Spawner UI.

Covers:
  - SubAgentWorkflow / ChildAgentConfig / ExecutionNode model validation
  - SpawnerService CRUD (create, list, get, delete)
  - SpawnerService execution: background delegation, success, failure
  - Execution tree status tracking (pending -> running -> completed/failed)
  - API route integration: CRUD, execute, status, auth enforcement
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from agent33.spawner.models import (
    ChildAgentConfig,
    ExecutionNode,
    ExecutionTree,
    IsolationMode,
    SubAgentWorkflow,
)
from agent33.spawner.service import SpawnerService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_delegation_manager() -> MagicMock:
    """Create a mock DelegationManager."""
    manager = MagicMock()
    manager.delegate = AsyncMock()
    return manager


def _make_delegation_result(
    *,
    status: str = "completed",
    raw_response: str = "Child completed successfully",
    error: str = "",
) -> MagicMock:
    """Create a mock DelegationResult."""
    result = MagicMock()
    result.status = MagicMock()
    result.status.value = status
    result.raw_response = raw_response
    result.error = error
    result.tokens_used = 100
    result.model = "test-model"
    result.duration_seconds = 1.5
    return result


@pytest.fixture()
def delegation_manager() -> MagicMock:
    return _make_delegation_manager()


@pytest.fixture()
def service(delegation_manager: MagicMock) -> SpawnerService:
    return SpawnerService(delegation_manager=delegation_manager)


def _make_workflow(
    *,
    name: str = "test-workflow",
    parent: str = "orchestrator",
    children: list[str] | None = None,
) -> SubAgentWorkflow:
    child_configs = [
        ChildAgentConfig(agent_name=c) for c in (children or ["code-worker", "researcher"])
    ]
    return SubAgentWorkflow(
        name=name,
        parent_agent=parent,
        children=child_configs,
    )


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------


class TestModels:
    """Model-level validation."""

    def test_isolation_mode_enum_values(self) -> None:
        assert IsolationMode.LOCAL == "local"
        assert IsolationMode.SUBPROCESS == "subprocess"
        assert IsolationMode.DOCKER == "docker"

    def test_child_agent_config_defaults(self) -> None:
        config = ChildAgentConfig(agent_name="test-agent")
        assert config.agent_name == "test-agent"
        assert config.system_prompt_override is None
        assert config.tool_allowlist == []
        assert config.autonomy_level == 1
        assert config.isolation == IsolationMode.LOCAL
        assert config.pack_names == []

    def test_child_agent_config_rejects_empty_name(self) -> None:
        with pytest.raises(ValidationError, match="String should have at least 1 character"):
            ChildAgentConfig(agent_name="")

    def test_child_agent_config_autonomy_bounds(self) -> None:
        # Valid boundaries
        config_min = ChildAgentConfig(agent_name="a", autonomy_level=0)
        assert config_min.autonomy_level == 0
        config_max = ChildAgentConfig(agent_name="a", autonomy_level=3)
        assert config_max.autonomy_level == 3

        # Out of bounds
        with pytest.raises(ValidationError, match="less than or equal to 3"):
            ChildAgentConfig(agent_name="a", autonomy_level=4)
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            ChildAgentConfig(agent_name="a", autonomy_level=-1)

    def test_workflow_generates_id(self) -> None:
        wf = SubAgentWorkflow(name="test", parent_agent="orchestrator")
        assert wf.id.startswith("wf-")
        assert len(wf.id) > 3

    def test_workflow_rejects_empty_name(self) -> None:
        with pytest.raises(ValidationError, match="String should have at least 1 character"):
            SubAgentWorkflow(name="", parent_agent="orchestrator")

    def test_workflow_rejects_empty_parent(self) -> None:
        with pytest.raises(ValidationError, match="String should have at least 1 character"):
            SubAgentWorkflow(name="test", parent_agent="")

    def test_execution_node_defaults(self) -> None:
        node = ExecutionNode(agent_name="test")
        assert node.status == "pending"
        assert node.started_at is None
        assert node.completed_at is None
        assert node.result_summary is None
        assert node.error is None
        assert node.children == []

    def test_execution_tree_generates_ids(self) -> None:
        tree = ExecutionTree(
            workflow_id="wf-123",
            root=ExecutionNode(agent_name="root"),
        )
        assert tree.execution_id.startswith("exec-")
        assert tree.status == "pending"


# ---------------------------------------------------------------------------
# SpawnerService CRUD tests
# ---------------------------------------------------------------------------


class TestSpawnerServiceCRUD:
    """Workflow CRUD operations."""

    def test_create_workflow(self, service: SpawnerService) -> None:
        wf = _make_workflow()
        saved = service.create_workflow(wf)
        assert saved.id == wf.id
        assert saved.name == "test-workflow"
        assert saved.parent_agent == "orchestrator"
        assert len(saved.children) == 2

    def test_create_duplicate_raises(self, service: SpawnerService) -> None:
        wf = _make_workflow()
        service.create_workflow(wf)
        with pytest.raises(ValueError, match="already exists"):
            service.create_workflow(wf)

    def test_get_workflow(self, service: SpawnerService) -> None:
        wf = _make_workflow()
        service.create_workflow(wf)
        retrieved = service.get_workflow(wf.id)
        assert retrieved is not None
        assert retrieved.id == wf.id
        assert retrieved.name == wf.name

    def test_get_nonexistent_returns_none(self, service: SpawnerService) -> None:
        assert service.get_workflow("nonexistent") is None

    def test_list_workflows_empty(self, service: SpawnerService) -> None:
        assert service.list_workflows() == []

    def test_list_workflows_ordered_by_created_at(self, service: SpawnerService) -> None:
        wf1 = _make_workflow(name="first")
        wf2 = _make_workflow(name="second")
        service.create_workflow(wf1)
        service.create_workflow(wf2)
        listed = service.list_workflows()
        assert len(listed) == 2
        # Most recent first
        assert listed[0].created_at >= listed[1].created_at

    def test_delete_workflow(self, service: SpawnerService) -> None:
        wf = _make_workflow()
        service.create_workflow(wf)
        assert service.delete_workflow(wf.id) is True
        assert service.get_workflow(wf.id) is None

    def test_delete_nonexistent_returns_false(self, service: SpawnerService) -> None:
        assert service.delete_workflow("nonexistent") is False


# ---------------------------------------------------------------------------
# SpawnerService execution tests
# ---------------------------------------------------------------------------


class TestSpawnerServiceExecution:
    """Execution and delegation behavior."""

    async def test_execute_creates_pending_tree(self, service: SpawnerService) -> None:
        wf = _make_workflow()
        service.create_workflow(wf)
        tree = service.execute_workflow(wf.id)

        assert tree.workflow_id == wf.id
        assert tree.status == "pending"
        assert tree.root.agent_name == "orchestrator"
        assert len(tree.root.children) == 2
        assert tree.root.children[0].agent_name == "code-worker"
        assert tree.root.children[1].agent_name == "researcher"
        # Allow the background task to complete
        await asyncio.sleep(0.1)

    async def test_execute_nonexistent_raises(self, service: SpawnerService) -> None:
        with pytest.raises(ValueError, match="not found"):
            service.execute_workflow("nonexistent")

    async def test_execute_completes_all_children(
        self, delegation_manager: MagicMock, service: SpawnerService
    ) -> None:
        delegation_manager.delegate.return_value = _make_delegation_result(
            status="completed", raw_response="Done"
        )
        wf = _make_workflow()
        service.create_workflow(wf)
        service.execute_workflow(wf.id)

        # Wait for background execution to complete
        await asyncio.sleep(0.5)

        # Re-fetch the tree from the service
        latest = service.get_latest_execution(wf.id)
        assert latest is not None
        assert latest.status == "completed"
        assert latest.root.status == "completed"
        for child in latest.root.children:
            assert child.status == "completed"
            assert child.result_summary == "Done"
            assert child.completed_at is not None

    async def test_execute_marks_failed_on_delegation_failure(
        self, delegation_manager: MagicMock, service: SpawnerService
    ) -> None:
        delegation_manager.delegate.return_value = _make_delegation_result(
            status="failed", error="Agent not found"
        )
        wf = _make_workflow(children=["missing-agent"])
        service.create_workflow(wf)
        service.execute_workflow(wf.id)

        await asyncio.sleep(0.5)

        latest = service.get_latest_execution(wf.id)
        assert latest is not None
        assert latest.status == "failed"
        assert latest.root.status == "failed"
        assert latest.root.children[0].status == "failed"
        assert latest.root.children[0].error is not None
        assert "Agent not found" in (latest.root.children[0].error or "")

    async def test_execute_handles_delegation_exception(
        self, delegation_manager: MagicMock, service: SpawnerService
    ) -> None:
        delegation_manager.delegate.side_effect = RuntimeError("Connection refused")
        wf = _make_workflow(children=["worker"])
        service.create_workflow(wf)
        service.execute_workflow(wf.id)

        await asyncio.sleep(0.5)

        latest = service.get_latest_execution(wf.id)
        assert latest is not None
        assert latest.status == "failed"
        assert latest.root.children[0].status == "failed"
        assert "Connection refused" in (latest.root.children[0].error or "")

    async def test_execute_partial_failure(
        self, delegation_manager: MagicMock, service: SpawnerService
    ) -> None:
        """One child succeeds, one fails -> overall status is failed."""
        call_count = 0

        async def side_effect(*args: Any, **kwargs: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_delegation_result(status="completed", raw_response="OK")
            return _make_delegation_result(status="failed", error="Timed out")

        delegation_manager.delegate.side_effect = side_effect
        wf = _make_workflow(children=["worker-a", "worker-b"])
        service.create_workflow(wf)
        service.execute_workflow(wf.id)

        await asyncio.sleep(0.5)

        latest = service.get_latest_execution(wf.id)
        assert latest is not None
        assert latest.status == "failed"
        assert latest.root.children[0].status == "completed"
        assert latest.root.children[1].status == "failed"

    async def test_get_latest_execution_returns_none_when_empty(
        self, service: SpawnerService
    ) -> None:
        wf = _make_workflow()
        service.create_workflow(wf)
        assert service.get_latest_execution(wf.id) is None

    async def test_execution_result_summary_truncated(
        self, delegation_manager: MagicMock, service: SpawnerService
    ) -> None:
        """Result summary is first 200 chars."""
        long_response = "x" * 500
        delegation_manager.delegate.return_value = _make_delegation_result(
            status="completed", raw_response=long_response
        )
        wf = _make_workflow(children=["worker"])
        service.create_workflow(wf)
        service.execute_workflow(wf.id)

        await asyncio.sleep(0.5)

        latest = service.get_latest_execution(wf.id)
        assert latest is not None
        child = latest.root.children[0]
        assert child.result_summary is not None
        assert len(child.result_summary) == 200

    async def test_shutdown_cancels_tasks(
        self, delegation_manager: MagicMock, service: SpawnerService
    ) -> None:
        """Shutdown cancels running background tasks."""

        # Make delegation slow
        async def slow_delegate(*args: Any, **kwargs: Any) -> MagicMock:
            await asyncio.sleep(10)
            return _make_delegation_result()

        delegation_manager.delegate.side_effect = slow_delegate
        wf = _make_workflow(children=["slow-worker"])
        service.create_workflow(wf)
        service.execute_workflow(wf.id)

        # Give the task time to start
        await asyncio.sleep(0.1)
        assert len(service._tasks) == 1

        await service.shutdown()
        # Tasks should be cleaned up
        assert len(service._tasks) == 0


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestSpawnerRoutes:
    """HTTP endpoint tests using httpx + ASGITransport."""

    @pytest.fixture()
    def _setup_app(self, delegation_manager: MagicMock) -> Any:
        """Install SpawnerService on the app for route tests."""
        from agent33.main import app

        spawner_service = SpawnerService(delegation_manager=delegation_manager)
        app.state.spawner_service = spawner_service

        # Install minimal auth state to bypass 401
        # The AuthMiddleware normally sets request.state.user
        return app, spawner_service

    @pytest.fixture()
    def auth_headers(self) -> dict[str, str]:
        """Create a JWT-like token for test auth."""
        import jwt

        payload = {
            "sub": "test-user",
            "tenant_id": "test-tenant",
            "scopes": [
                "admin",
                "agents:read",
                "agents:write",
                "agents:invoke",
            ],
        }
        from agent33.config import settings

        token = jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}

    async def test_create_workflow_returns_201(
        self, _setup_app: Any, auth_headers: dict[str, str]
    ) -> None:
        import httpx

        app, _ = _setup_app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/spawner/workflows",
                json={
                    "name": "test-workflow",
                    "description": "A test",
                    "parent_agent": "orchestrator",
                    "children": [
                        {"agent_name": "code-worker", "isolation": "local", "autonomy_level": 2}
                    ],
                },
                headers=auth_headers,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-workflow"
        assert data["parent_agent"] == "orchestrator"
        assert len(data["children"]) == 1
        assert data["children"][0]["agent_name"] == "code-worker"
        assert data["children"][0]["autonomy_level"] == 2
        assert data["id"].startswith("wf-")

    async def test_list_workflows(self, _setup_app: Any, auth_headers: dict[str, str]) -> None:
        import httpx

        app, svc = _setup_app
        svc.create_workflow(_make_workflow(name="wf-a"))
        svc.create_workflow(_make_workflow(name="wf-b"))

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/spawner/workflows", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {d["name"] for d in data}
        assert "wf-a" in names
        assert "wf-b" in names

    async def test_get_workflow_by_id(self, _setup_app: Any, auth_headers: dict[str, str]) -> None:
        import httpx

        app, svc = _setup_app
        wf = _make_workflow(name="fetched-wf")
        svc.create_workflow(wf)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/v1/spawner/workflows/{wf.id}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "fetched-wf"

    async def test_get_nonexistent_returns_404(
        self, _setup_app: Any, auth_headers: dict[str, str]
    ) -> None:
        import httpx

        app, _ = _setup_app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/spawner/workflows/wf-nope", headers=auth_headers)
        assert resp.status_code == 404

    async def test_delete_workflow_returns_deleted(
        self, _setup_app: Any, auth_headers: dict[str, str]
    ) -> None:
        import httpx

        app, svc = _setup_app
        wf = _make_workflow(name="to-delete")
        svc.create_workflow(wf)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(f"/v1/spawner/workflows/{wf.id}", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True
        assert data["workflow_id"] == wf.id

    async def test_delete_nonexistent_returns_404(
        self, _setup_app: Any, auth_headers: dict[str, str]
    ) -> None:
        import httpx

        app, _ = _setup_app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete("/v1/spawner/workflows/wf-nope", headers=auth_headers)
        assert resp.status_code == 404

    async def test_execute_returns_execution_tree(
        self,
        _setup_app: Any,
        auth_headers: dict[str, str],
        delegation_manager: MagicMock,
    ) -> None:
        import httpx

        app, svc = _setup_app
        delegation_manager.delegate.return_value = _make_delegation_result()
        wf = _make_workflow(name="exec-test")
        svc.create_workflow(wf)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/v1/spawner/workflows/{wf.id}/execute", headers=auth_headers
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == wf.id
        assert data["execution_id"].startswith("exec-")
        assert data["root"]["agent_name"] == "orchestrator"
        assert len(data["root"]["children"]) == 2

        # Wait for background task to complete
        await asyncio.sleep(0.5)

    async def test_execute_nonexistent_returns_404(
        self, _setup_app: Any, auth_headers: dict[str, str]
    ) -> None:
        import httpx

        app, _ = _setup_app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/v1/spawner/workflows/wf-nope/execute", headers=auth_headers)
        assert resp.status_code == 404

    async def test_status_returns_latest_tree(
        self,
        _setup_app: Any,
        auth_headers: dict[str, str],
        delegation_manager: MagicMock,
    ) -> None:
        import httpx

        app, svc = _setup_app
        delegation_manager.delegate.return_value = _make_delegation_result()
        wf = _make_workflow(name="status-test")
        svc.create_workflow(wf)
        svc.execute_workflow(wf.id)

        await asyncio.sleep(0.5)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/v1/spawner/workflows/{wf.id}/status", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["root"]["status"] == "completed"

    async def test_status_no_execution_returns_404(
        self, _setup_app: Any, auth_headers: dict[str, str]
    ) -> None:
        import httpx

        app, svc = _setup_app
        wf = _make_workflow(name="no-exec")
        svc.create_workflow(wf)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/v1/spawner/workflows/{wf.id}/status", headers=auth_headers)
        assert resp.status_code == 404

    async def test_no_auth_returns_401(self, _setup_app: Any) -> None:
        """Unauthenticated requests get 401."""
        import httpx

        app, _ = _setup_app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/v1/spawner/workflows")
        assert resp.status_code == 401

    async def test_create_with_invalid_body_returns_422(
        self, _setup_app: Any, auth_headers: dict[str, str]
    ) -> None:
        import httpx

        app, _ = _setup_app
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/spawner/workflows",
                json={"name": "", "parent_agent": ""},  # Both empty = validation error
                headers=auth_headers,
            )
        assert resp.status_code == 422
