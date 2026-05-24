"""Phase 23 workspace/project API tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.sessions.models import OperatorSessionStatus
from agent33.workspaces.models import WorkspaceProject, WorkspaceRecord
from agent33.workspaces.repository import (
    InMemoryWorkspaceRepository,
    SqliteWorkspaceRepository,
    get_workspace_repository,
    set_workspace_repository,
)


@pytest.fixture(autouse=True)
def isolated_workspace_repository():
    original = get_workspace_repository()
    set_workspace_repository(InMemoryWorkspaceRepository())
    yield
    set_workspace_repository(original)


def _client(subject: str, scopes: list[str], tenant_id: str = "") -> TestClient:
    token = create_access_token(subject, scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def tenant_a_client() -> TestClient:
    return _client(
        "tenant-a-user",
        scopes=["workspaces:read", "workspaces:write"],
        tenant_id="tenant-a",
    )


@pytest.fixture
def tenant_b_client() -> TestClient:
    return _client(
        "tenant-b-user",
        scopes=["workspaces:read", "workspaces:write"],
        tenant_id="tenant-b",
    )


@pytest.fixture
def admin_client() -> TestClient:
    return _client("admin-user", scopes=["admin"])


def _workspace_create_headers(client: TestClient, route_approval_headers) -> dict[str, str]:
    return route_approval_headers(
        client,
        route_name="workspaces.create",
        operation="create",
        arguments={
            "workspace_id": "tenant-a-build",
            "name": "Tenant A Build",
            "template": "Solo Builder",
            "goal": "Tenant-scoped implementation",
            "status": "Planning",
            "tenant_id": "tenant-a",
            "owner": "owner-a",
            "agents": 1,
            "tasks": 2,
            "metadata": {"phase": "23"},
        },
        details="pytest workspace create",
    )


def test_workspace_api_lists_shared_templates(tenant_a_client: TestClient) -> None:
    response = tenant_a_client.get("/v1/workspaces/")

    assert response.status_code == 200
    payload = response.json()
    assert [workspace["id"] for workspace in payload][:4] == [
        "solo-builder",
        "research-build",
        "test-review",
        "shipyard",
    ]


def test_workspace_create_requires_approval(tenant_a_client: TestClient) -> None:
    response = tenant_a_client.post(
        "/v1/workspaces/",
        json={
            "workspace_id": "tenant-a-build",
            "name": "Tenant A Build",
            "tenant_id": "tenant-a",
        },
    )

    assert response.status_code == 428
    assert response.json()["detail"]["approval_header"] == "X-Agent33-Approval-Token"


def test_workspace_crud_is_tenant_scoped(
    tenant_a_client: TestClient,
    tenant_b_client: TestClient,
    admin_client: TestClient,
    route_approval_headers,
) -> None:
    create_body = {
        "workspace_id": "tenant-a-build",
        "name": "Tenant A Build",
        "template": "Solo Builder",
        "goal": "Tenant-scoped implementation",
        "status": "Planning",
        "tenant_id": "tenant-a",
        "owner": "owner-a",
        "agents": 1,
        "tasks": 2,
        "metadata": {"phase": "23"},
    }
    create_response = tenant_a_client.post(
        "/v1/workspaces/",
        json=create_body,
        headers=_workspace_create_headers(tenant_a_client, route_approval_headers),
    )
    assert create_response.status_code == 201, create_response.text
    assert create_response.json()["tenant_id"] == "tenant-a"

    tenant_b_get = tenant_b_client.get("/v1/workspaces/tenant-a-build")
    assert tenant_b_get.status_code == 403

    tenant_b_list = tenant_b_client.get("/v1/workspaces/")
    assert "tenant-a-build" not in [workspace["id"] for workspace in tenant_b_list.json()]

    admin_list = admin_client.get("/v1/workspaces/")
    assert "tenant-a-build" in [workspace["id"] for workspace in admin_list.json()]

    update_body = {"status": "Running", "tasks": 4}
    update_response = tenant_a_client.patch(
        "/v1/workspaces/tenant-a-build",
        json=update_body,
        headers=route_approval_headers(
            tenant_a_client,
            route_name="workspaces.update",
            operation="update",
            arguments={**update_body, "workspace_id": "tenant-a-build"},
            details="pytest workspace update",
        ),
    )
    assert update_response.status_code == 200
    assert update_response.json()["status"] == "Running"
    assert update_response.json()["tasks"] == 4


def test_workspace_projects_inherit_tenant_scope(
    tenant_a_client: TestClient,
    tenant_b_client: TestClient,
    route_approval_headers,
) -> None:
    project_body = {
        "project_id": "tenant-a-project",
        "name": "Tenant A Project",
        "status": "active",
        "owner": "owner-a",
        "session_ids": ["session-a"],
        "metadata": {"artifacts": ["report.md"]},
    }
    create_response = tenant_a_client.post(
        "/v1/workspaces/solo-builder/projects",
        json=project_body,
        headers=route_approval_headers(
            tenant_a_client,
            route_name="workspaces.projects.create",
            operation="create",
            arguments={**project_body, "workspace_id": "solo-builder"},
            details="pytest workspace project create",
        ),
    )
    assert create_response.status_code == 201, create_response.text
    assert create_response.json()["tenant_id"] == "tenant-a"

    tenant_a_projects = tenant_a_client.get("/v1/workspaces/solo-builder/projects")
    assert [project["project_id"] for project in tenant_a_projects.json()] == ["tenant-a-project"]

    tenant_b_projects = tenant_b_client.get("/v1/workspaces/solo-builder/projects")
    assert tenant_b_projects.status_code == 200
    assert tenant_b_projects.json() == []


def test_workspace_recovery_reads_live_session_state(
    tenant_a_client: TestClient,
) -> None:
    class FakeSessionService:
        async def list_sessions(self, status=None, limit=50, tenant_id=None):
            assert tenant_id == "tenant-a"
            return [
                SimpleNamespace(
                    session_id="session-recovery",
                    purpose="Recover build lane",
                    status=OperatorSessionStatus.CRASHED,
                    context={
                        "workspace_id": "solo-builder",
                        "artifacts": ["trace.json", "handoff.md"],
                    },
                    task_count=2,
                    event_count=5,
                )
            ]

    had_service = hasattr(app.state, "operator_session_service")
    previous_service = getattr(app.state, "operator_session_service", None)
    app.state.operator_session_service = FakeSessionService()
    try:
        response = tenant_a_client.get("/v1/workspaces/solo-builder/recovery")
    finally:
        if had_service:
            app.state.operator_session_service = previous_service
        else:
            delattr(app.state, "operator_session_service")

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace_id"] == "solo-builder"
    assert payload["primary_message"] == "1 recovery checkpoint requires attention."
    assert payload["snapshots"][0] == {
        "id": "session-recovery",
        "label": "Recover build lane",
        "status": "blocked",
        "resume_action": "Resume session",
        "rollback_action": "Restore latest checkpoint",
        "budget_label": "2 tasks / 5 events",
        "artifact_count": 2,
        "source": "session",
    }


def test_sqlite_workspace_repository_persists_workspaces_and_projects(tmp_path) -> None:
    db_path = tmp_path / "workspaces.db"
    repo = SqliteWorkspaceRepository(str(db_path), seed_defaults=False)
    repo.create_workspace(
        WorkspaceRecord(
            workspace_id="tenant-a-build",
            name="Tenant A Build",
            template="Solo Builder",
            goal="Durable lifecycle",
            status="Planning",
            tenant_id="tenant-a",
            owner="owner-a",
        )
    )
    repo.create_project(
        WorkspaceProject(
            project_id="tenant-a-project",
            workspace_id="tenant-a-build",
            name="Tenant A Project",
            tenant_id="tenant-a",
            owner="owner-a",
            session_ids=["session-a"],
        )
    )
    repo.close()

    reopened = SqliteWorkspaceRepository(str(db_path), seed_defaults=False)
    try:
        workspace = reopened.get_workspace("tenant-a-build")
        assert workspace is not None
        assert workspace.tenant_id == "tenant-a"
        assert workspace.project_ids == ["tenant-a-project"]
        assert reopened.list_workspaces(tenant_id="tenant-b") == []

        projects = reopened.list_projects("tenant-a-build", tenant_id="tenant-a")
        assert [project.project_id for project in projects] == ["tenant-a-project"]
        assert reopened.list_projects("tenant-a-build", tenant_id="tenant-b") == []
    finally:
        reopened.close()
