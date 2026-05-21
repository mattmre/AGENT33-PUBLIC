"""Tests for IDOR access control and scope enforcement."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.api.route_approvals import APPROVAL_TOKEN_HEADER
from agent33.main import app
from agent33.security.auth import (
    _api_keys,
    create_access_token,
    generate_api_key,
)


@pytest.fixture
def admin_client() -> TestClient:
    """Client with admin scopes."""
    token = create_access_token("admin-user", scopes=["admin"])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def reader_client() -> TestClient:
    """Client with only read scopes."""
    token = create_access_token("reader-user", scopes=["agents:read", "workflows:read"])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def no_scope_client() -> TestClient:
    """Client with no scopes."""
    token = create_access_token("no-scope-user", scopes=[])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def invoker_client() -> TestClient:
    """Client with invoke scope only."""
    token = create_access_token("invoker-user", scopes=["agents:invoke"])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(autouse=True)
def reset_tool_approval_service() -> None:
    from agent33.api.routes.tool_approvals import _reset_tool_approval_service

    _reset_tool_approval_service()
    yield
    _reset_tool_approval_service()


def _approve_api_key_creation(client: TestClient, payload: dict[str, object]) -> str:
    pending = client.post("/v1/auth/api-keys", json=payload)
    assert pending.status_code == 428
    approval_id = pending.json()["detail"]["approval_id"]

    decision = client.post(
        f"/v1/approvals/tools/{approval_id}/decision",
        json={"decision": "approve"},
    )
    assert decision.status_code == 200

    token_response = client.post(
        f"/v1/approvals/tools/{approval_id}/token",
        json={"token_preset": "single_use"},
    )
    assert token_response.status_code == 200
    return token_response.json()["approval_token"]


# --- Agent endpoint scope tests ---


class TestAgentScopes:
    def test_list_agents_requires_read_scope(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.get("/v1/agents/")
        assert resp.status_code == 403
        assert "agents:read" in resp.json()["detail"]

    def test_list_agents_allowed_with_read_scope(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/agents/")
        assert resp.status_code == 200

    def test_list_agents_allowed_with_admin(self, admin_client: TestClient) -> None:
        resp = admin_client.get("/v1/agents/")
        assert resp.status_code == 200

    def test_get_agent_requires_read_scope(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.get("/v1/agents/orchestrator")
        # 403 because scope is checked before route handler (404 would come later)
        assert resp.status_code == 403

    def test_get_agent_by_id_requires_read_scope(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.get("/v1/agents/by-id/AGT-001")
        assert resp.status_code == 403

    def test_invoke_requires_invoke_scope(self, reader_client: TestClient) -> None:
        """Reader scope should NOT be able to invoke agents."""
        resp = reader_client.post(
            "/v1/agents/orchestrator/invoke",
            json={"inputs": {"task": "test"}},
        )
        assert resp.status_code == 403
        assert "agents:invoke" in resp.json()["detail"]

    def test_capabilities_catalog_is_public(self, no_scope_client: TestClient) -> None:
        """Capabilities catalog does NOT require scope."""
        resp = no_scope_client.get("/v1/agents/capabilities/catalog")
        assert resp.status_code == 200

    def test_search_agents_requires_read_scope(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.get("/v1/agents/search")
        assert resp.status_code == 403
        assert "agents:read" in resp.json()["detail"]

    def test_register_agent_requires_write_scope(self, reader_client: TestClient) -> None:
        resp = reader_client.post(
            "/v1/agents/",
            json={
                "name": "test-agent",
                "version": "1.0",
                "role": "worker",
                "description": "test",
            },
        )
        assert resp.status_code == 403
        assert "agents:write" in resp.json()["detail"]

    def test_admin_register_agent_requires_approval_token(
        self,
        admin_client: TestClient,
        sample_agent_def,
    ) -> None:
        payload = dict(sample_agent_def)
        payload["name"] = "approved-agent"
        resp = admin_client.post("/v1/agents/", json=payload)
        assert resp.status_code == 428
        detail = resp.json()["detail"]
        assert detail["approval_id"].startswith("APR-")
        assert detail["approval_header"] == APPROVAL_TOKEN_HEADER

    def test_admin_can_register_agent_with_approval(
        self,
        admin_client: TestClient,
        sample_agent_def,
        route_approval_headers,
    ) -> None:
        payload = dict(sample_agent_def)
        payload["name"] = "approved-agent"
        resp = admin_client.post(
            "/v1/agents/",
            json=payload,
            headers=route_approval_headers(
                admin_client,
                route_name="agents.create",
                operation="create",
                arguments=payload,
                details="Pytest admin agent registration",
            ),
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "approved-agent"


# --- Workflow endpoint scope tests ---


class TestWorkflowScopes:
    def test_list_workflows_requires_read_scope(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.get("/v1/workflows/")
        assert resp.status_code == 403
        assert "workflows:read" in resp.json()["detail"]

    def test_list_workflows_allowed_with_scope(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/workflows/")
        assert resp.status_code == 200

    def test_get_workflow_requires_read_scope(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.get("/v1/workflows/test-workflow")
        assert resp.status_code == 403

    def test_execute_workflow_requires_execute_scope(self, reader_client: TestClient) -> None:
        resp = reader_client.post(
            "/v1/workflows/test/execute",
            json={"inputs": {}},
        )
        assert resp.status_code == 403
        assert "workflows:execute" in resp.json()["detail"]

    def test_create_workflow_requires_write_scope(self, reader_client: TestClient) -> None:
        resp = reader_client.post(
            "/v1/workflows/",
            json={
                "name": "test-wf",
                "version": "1.0",
                "steps": [],
            },
        )
        assert resp.status_code == 403
        assert "workflows:write" in resp.json()["detail"]

    def test_admin_create_workflow_requires_approval_token(self, admin_client: TestClient) -> None:
        payload = {
            "name": "approved-workflow",
            "version": "1.0.0",
            "description": "approval required",
            "steps": [{"id": "step-1", "action": "transform", "transform": "inputs"}],
            "execution": {"mode": "sequential"},
        }
        resp = admin_client.post("/v1/workflows/", json=payload)
        assert resp.status_code == 428
        detail = resp.json()["detail"]
        assert detail["approval_id"].startswith("APR-")
        assert detail["approval_header"] == APPROVAL_TOKEN_HEADER

    def test_admin_can_create_workflow_with_approval(
        self,
        admin_client: TestClient,
        route_approval_headers,
    ) -> None:
        payload = {
            "name": "approved-workflow",
            "version": "1.0.0",
            "description": "approval required",
            "steps": [{"id": "step-1", "action": "transform", "transform": "inputs"}],
            "execution": {"mode": "sequential"},
        }
        resp = admin_client.post(
            "/v1/workflows/",
            json=payload,
            headers=route_approval_headers(
                admin_client,
                route_name="workflows.create",
                operation="create",
                arguments=payload,
                details="Pytest admin workflow registration",
            ),
        )
        assert resp.status_code == 201
        assert resp.json()["name"] == "approved-workflow"


# --- Memory endpoint scope tests ---


class TestMemoryScopes:
    def test_search_memory_requires_scope(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.post(
            "/v1/memory/search",
            json={"query": "test"},
        )
        assert resp.status_code == 403

    def test_list_observations_requires_scope(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.get("/v1/memory/sessions/test-session/observations")
        assert resp.status_code == 403

    def test_summarize_requires_write_scope(self, reader_client: TestClient) -> None:
        resp = reader_client.post("/v1/memory/sessions/test-session/summarize")
        assert resp.status_code == 403


# --- API key ownership tests ---


class TestApiKeyOwnership:
    @pytest.fixture(autouse=True)
    def cleanup_api_keys(self):
        """Clean up API keys after each test."""
        yield
        _api_keys.clear()

    def test_admin_create_api_key_requires_approval_token(self, admin_client: TestClient) -> None:
        resp = admin_client.post(
            "/v1/auth/api-keys",
            json={"subject": "test-user", "scopes": ["agents:read"]},
        )
        assert resp.status_code == 428
        detail = resp.json()["detail"]
        assert detail["approval_id"].startswith("APR-")
        assert detail["approval_header"] == APPROVAL_TOKEN_HEADER

    def test_admin_can_create_api_key(self, admin_client: TestClient) -> None:
        payload = {"subject": "test-user", "scopes": ["agents:read"]}
        approval_token = _approve_api_key_creation(admin_client, payload)

        resp = admin_client.post(
            "/v1/auth/api-keys",
            json=payload,
            headers={APPROVAL_TOKEN_HEADER: approval_token},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "key_id" in data
        assert data["subject"] == "test-user"
        assert data["scopes"] == ["agents:read"]

    def test_non_admin_cannot_create_api_key(self, reader_client: TestClient) -> None:
        resp = reader_client.post(
            "/v1/auth/api-keys",
            json={"subject": "test-user", "scopes": ["agents:read"]},
        )
        assert resp.status_code == 403

    def test_admin_revoke_any_key_requires_approval_token(self, admin_client: TestClient) -> None:
        result = generate_api_key("other-user", scopes=[])
        key_id = result["key_id"]

        resp = admin_client.delete(f"/v1/auth/api-keys/{key_id}")
        assert resp.status_code == 428
        detail = resp.json()["detail"]
        assert detail["approval_id"].startswith("APR-")
        assert detail["approval_header"] == APPROVAL_TOKEN_HEADER

    def test_admin_can_revoke_any_key(
        self, admin_client: TestClient, route_approval_headers
    ) -> None:
        # Create a key
        payload = {"subject": "other-user", "scopes": []}
        approval_token = _approve_api_key_creation(admin_client, payload)
        resp = admin_client.post(
            "/v1/auth/api-keys",
            json=payload,
            headers={APPROVAL_TOKEN_HEADER: approval_token},
        )
        key_id = resp.json()["key_id"]
        # Admin can revoke it
        resp = admin_client.delete(
            f"/v1/auth/api-keys/{key_id}",
            headers=route_approval_headers(
                admin_client,
                route_name="auth.api_keys.delete",
                operation="delete",
                arguments={"key_id": key_id},
                details="Pytest admin API key revoke",
            ),
        )
        assert resp.status_code == 204

    def test_user_cannot_revoke_others_key(self) -> None:
        # Create a key for user-A
        result = generate_api_key("user-a", scopes=["agents:read"])
        key_id = result["key_id"]
        # Try to revoke as user-B (non-admin)
        token = create_access_token("user-b", scopes=["agents:read"])
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
        resp = client.delete(f"/v1/auth/api-keys/{key_id}")
        assert resp.status_code == 404  # Not found because not owned

    def test_user_can_revoke_own_key(self) -> None:
        # Create a key for user-A
        result = generate_api_key("user-a", scopes=["agents:read"])
        key_id = result["key_id"]
        # Revoke as user-A (non-admin, but owner)
        token = create_access_token("user-a", scopes=["agents:read"])
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
        resp = client.delete(f"/v1/auth/api-keys/{key_id}")
        assert resp.status_code == 204


# --- Production secrets enforcement ---


class TestProductionSecrets:
    def test_development_mode_allows_default_secrets(self) -> None:
        from agent33.config import Settings

        s = Settings(environment="development")
        warnings = s.check_production_secrets()
        # Should return warnings but not raise
        assert len(warnings) > 0

    def test_production_mode_rejects_default_secrets(self) -> None:
        from pydantic import SecretStr

        from agent33.config import Settings

        with pytest.raises(SystemExit, match="jwt_secret must be changed"):
            Settings(
                environment="production",
                jwt_secret=SecretStr("change-me-in-production"),
            )

    def test_production_mode_rejects_other_default_secrets(self) -> None:
        from pydantic import SecretStr

        from agent33.config import Settings

        s = Settings(
            environment="production",
            api_secret_key=SecretStr("change-me-in-production"),
            jwt_secret="my-real-jwt-secret-67890",
            auth_bootstrap_enabled=False,
            auth_bootstrap_admin_password="boot-secret-12345",
        )
        with pytest.raises(RuntimeError, match="FATAL"):
            s.check_production_secrets()

    def test_production_mode_accepts_custom_secrets(self) -> None:
        from agent33.config import Settings

        s = Settings(
            environment="production",
            api_secret_key="my-real-secret-key-12345",
            jwt_secret="my-real-jwt-secret-67890",
            auth_bootstrap_enabled=False,
            auth_bootstrap_admin_password="boot-secret-12345",
        )
        warnings = s.check_production_secrets()
        assert len(warnings) == 0


# --- Password hashing upgrade ---


class TestPasswordHashing:
    def test_login_uses_pbkdf2_not_sha256(self) -> None:
        """Verify that pbkdf2_hmac is used for password hashing (not plain SHA-256)."""
        import hashlib

        from agent33.api.routes.auth import _users

        password = "test-password-123"
        password_hash = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), b"agent33-salt", 100_000
        ).hex()
        _users["hash-test-user"] = {
            "password_hash": password_hash,
            "scopes": ["agents:read"],
        }
        try:
            client = TestClient(app)
            resp = client.post(
                "/v1/auth/token",
                json={"username": "hash-test-user", "password": password},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "access_token" in data
            assert data["token_type"] == "bearer"
        finally:
            _users.pop("hash-test-user", None)

    def test_login_wrong_password_fails(self) -> None:
        import hashlib

        from agent33.api.routes.auth import _users

        password_hash = hashlib.pbkdf2_hmac(
            "sha256", b"correct-password", b"agent33-salt", 100_000
        ).hex()
        _users["pw-test-user"] = {
            "password_hash": password_hash,
            "scopes": [],
        }
        try:
            client = TestClient(app)
            resp = client.post(
                "/v1/auth/token",
                json={"username": "pw-test-user", "password": "wrong-password"},
            )
            assert resp.status_code == 401
        finally:
            _users.pop("pw-test-user", None)

    def test_sha256_hash_no_longer_works(self) -> None:
        """Verify that a plain SHA-256 hash will NOT authenticate (regression guard)."""
        import hashlib

        from agent33.api.routes.auth import _users

        password = "some-password"
        # Old-style SHA-256 hash (what the code used before the fix)
        old_hash = hashlib.sha256(password.encode()).hexdigest()
        _users["sha256-test-user"] = {
            "password_hash": old_hash,
            "scopes": [],
        }
        try:
            client = TestClient(app)
            resp = client.post(
                "/v1/auth/token",
                json={"username": "sha256-test-user", "password": password},
            )
            # Should fail because the code now uses pbkdf2_hmac, not sha256
            assert resp.status_code == 401
        finally:
            _users.pop("sha256-test-user", None)
