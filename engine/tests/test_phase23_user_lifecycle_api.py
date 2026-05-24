"""Phase 23 user lifecycle API tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token, verify_token
from agent33.security.auth_repository import (
    InMemoryAuthRepository,
    get_auth_repository,
    set_auth_repository,
)


@pytest.fixture(autouse=True)
def isolated_auth_repository():
    original = get_auth_repository()
    set_auth_repository(InMemoryAuthRepository())
    yield
    set_auth_repository(original)


@pytest.fixture
def admin_client() -> TestClient:
    token = create_access_token("admin-user", scopes=["admin"], tenant_id="platform")
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _create_user(
    client: TestClient,
    route_approval_headers,
    *,
    username: str = "alice",
    tenant_id: str = "tenant-a",
) -> dict[str, object]:
    approval_args = {
        "username": username,
        "tenant_id": tenant_id,
        "role": "user",
        "scopes": ["workspaces:read", "sessions:read"],
        "enabled": True,
    }
    body = {**approval_args, "password": "CorrectHorse1!"}
    response = client.post(
        "/v1/users/",
        json=body,
        headers=route_approval_headers(
            client,
            route_name="users.create",
            operation="create",
            arguments=approval_args,
            details="pytest user lifecycle create",
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_user_create_requires_approval(admin_client: TestClient) -> None:
    body = {
        "username": "alice",
        "password": "CorrectHorse1!",
        "tenant_id": "tenant-a",
        "role": "user",
        "scopes": ["workspaces:read"],
        "enabled": True,
    }

    response = admin_client.post("/v1/users/", json=body)

    assert response.status_code == 428
    assert response.json()["detail"]["approval_header"] == "X-Agent33-Approval-Token"


def test_create_disable_enable_and_login_flow(
    admin_client: TestClient,
    route_approval_headers,
) -> None:
    created = _create_user(admin_client, route_approval_headers)
    assert created == {
        "username": "alice",
        "tenant_id": "tenant-a",
        "role": "user",
        "scopes": ["workspaces:read", "sessions:read"],
        "enabled": True,
    }

    public_client = TestClient(app)
    login_response = public_client.post(
        "/v1/auth/token",
        json={"username": "alice", "password": "CorrectHorse1!"},
    )
    assert login_response.status_code == 200
    token_payload = verify_token(login_response.json()["access_token"])
    assert token_payload.tenant_id == "tenant-a"
    assert token_payload.scopes == ["workspaces:read", "sessions:read"]

    disable_response = admin_client.post(
        "/v1/users/alice/disable",
        headers=route_approval_headers(
            admin_client,
            route_name="users.disable",
            operation="disable",
            arguments={"username": "alice", "enabled": False},
            details="pytest user disable",
        ),
    )
    assert disable_response.status_code == 200
    assert disable_response.json()["enabled"] is False

    disabled_login = public_client.post(
        "/v1/auth/token",
        json={"username": "alice", "password": "CorrectHorse1!"},
    )
    assert disabled_login.status_code == 401

    enable_response = admin_client.post(
        "/v1/users/alice/enable",
        headers=route_approval_headers(
            admin_client,
            route_name="users.enable",
            operation="enable",
            arguments={"username": "alice", "enabled": True},
            details="pytest user enable",
        ),
    )
    assert enable_response.status_code == 200
    assert enable_response.json()["enabled"] is True


def test_role_assignment_and_tenant_reassignment_are_public_api_operations(
    admin_client: TestClient,
    route_approval_headers,
) -> None:
    _create_user(admin_client, route_approval_headers)

    role_response = admin_client.post(
        "/v1/users/alice/roles",
        json={"role": "admin", "scopes": ["workspaces:read"]},
        headers=route_approval_headers(
            admin_client,
            route_name="users.roles.assign",
            operation="assign",
            arguments={
                "username": "alice",
                "role": "admin",
                "scopes": ["admin", "workspaces:read"],
            },
            details="pytest role assignment",
        ),
    )
    assert role_response.status_code == 200
    assert role_response.json()["role"] == "admin"
    assert role_response.json()["scopes"] == ["admin", "workspaces:read"]

    tenant_response = admin_client.post(
        "/v1/users/alice/tenant",
        json={"tenant_id": "tenant-b"},
        headers=route_approval_headers(
            admin_client,
            route_name="users.tenant.assign",
            operation="assign",
            arguments={"username": "alice", "tenant_id": "tenant-b"},
            details="pytest tenant reassignment",
        ),
    )
    assert tenant_response.status_code == 200
    assert tenant_response.json()["tenant_id"] == "tenant-b"

    users_response = admin_client.get("/v1/users/?tenant_id=tenant-b")
    assert users_response.status_code == 200
    assert [user["username"] for user in users_response.json()] == ["alice"]
