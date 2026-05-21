"""Tests for P66: Agent Builder API endpoints (PUT, DELETE, preview-prompt, validate).

Covers update, delete, prompt preview, and validation endpoints with real JWT auth
and in-memory registry state, following the pattern established in test_agent_profiling.py.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.agents.definition import AgentDefinition
from agent33.agents.registry import AgentRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_headers(scopes: list[str] | None = None) -> dict[str, str]:
    """Create valid JWT auth headers with the given scopes."""
    from agent33.security.auth import create_access_token

    effective_scopes = (
        scopes if scopes is not None else ["admin", "agents:read", "agents:write", "agents:invoke"]
    )
    token = create_access_token(
        "test-user",
        scopes=effective_scopes,
        tenant_id="t-test",
    )
    return {"Authorization": f"Bearer {token}"}


def _make_definition(
    name: str = "test-agent",
    version: str = "1.0.0",
    role: str = "implementer",
    description: str = "A test agent",
) -> AgentDefinition:
    return AgentDefinition(
        name=name,
        version=version,
        role=role,
        description=description,
        capabilities=[],
        inputs={},
        outputs={},
    )


def _definition_payload(
    name: str = "test-agent",
    version: str = "1.0.0",
    role: str = "implementer",
    description: str = "A test agent",
) -> dict:
    """Return a JSON-serializable dict for request bodies."""
    return {
        "name": name,
        "version": version,
        "role": role,
        "description": description,
        "capabilities": [],
        "inputs": {},
        "outputs": {},
    }


# ---------------------------------------------------------------------------
# PUT /{name} — Update agent
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    @pytest.fixture(autouse=True)
    def _restore_registry(self) -> None:  # type: ignore[misc]
        from agent33.main import app

        original = getattr(app.state, "agent_registry", None)
        yield
        if original is not None:
            app.state.agent_registry = original
        elif hasattr(app.state, "agent_registry"):
            del app.state.agent_registry

    async def test_update_existing_agent(self, route_approval_headers) -> None:
        from agent33.main import app

        registry = AgentRegistry()
        registry.register(_make_definition(description="Original description"))
        app.state.agent_registry = registry

        payload = _definition_payload(description="Updated description")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = _auth_headers()
            resp = await client.put(
                "/v1/agents/test-agent",
                json=payload,
                headers=route_approval_headers(
                    client,
                    route_name="agents.update",
                    operation="update",
                    arguments={"name": "test-agent", "definition": payload},
                    details="Pytest agent update",
                    authorization=headers["Authorization"],
                ),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "test-agent"
        assert data["description"] == "Updated description"

        # Verify the registry was actually updated
        updated = registry.get("test-agent")
        assert updated is not None
        assert updated.description == "Updated description"

    async def test_update_nonexistent_agent_returns_404(self, route_approval_headers) -> None:
        from agent33.main import app

        registry = AgentRegistry()
        app.state.agent_registry = registry

        payload = _definition_payload(name="ghost-agent")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = _auth_headers()
            resp = await client.put(
                "/v1/agents/ghost-agent",
                json=payload,
                headers=route_approval_headers(
                    client,
                    route_name="agents.update",
                    operation="update",
                    arguments={"name": "ghost-agent", "definition": payload},
                    details="Pytest missing agent update",
                    authorization=headers["Authorization"],
                ),
            )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_update_returns_full_definition(self, route_approval_headers) -> None:
        from agent33.main import app

        registry = AgentRegistry()
        registry.register(_make_definition())
        app.state.agent_registry = registry

        payload = _definition_payload(version="2.0.0", description="Upgraded")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = _auth_headers()
            resp = await client.put(
                "/v1/agents/test-agent",
                json=payload,
                headers=route_approval_headers(
                    client,
                    route_name="agents.update",
                    operation="update",
                    arguments={"name": "test-agent", "definition": payload},
                    details="Pytest full update response",
                    authorization=headers["Authorization"],
                ),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "2.0.0"
        assert data["role"] == "implementer"

    async def test_update_without_write_scope_returns_403(self) -> None:
        from agent33.main import app

        registry = AgentRegistry()
        registry.register(_make_definition())
        app.state.agent_registry = registry

        payload = _definition_payload(description="Should fail")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put(
                "/v1/agents/test-agent",
                json=payload,
                headers=_auth_headers(scopes=["agents:read"]),
            )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /{name} — Remove agent
# ---------------------------------------------------------------------------


class TestDeleteAgent:
    @pytest.fixture(autouse=True)
    def _restore_registry(self) -> None:  # type: ignore[misc]
        from agent33.main import app

        original = getattr(app.state, "agent_registry", None)
        yield
        if original is not None:
            app.state.agent_registry = original
        elif hasattr(app.state, "agent_registry"):
            del app.state.agent_registry

    async def test_delete_existing_agent(self, route_approval_headers) -> None:
        from agent33.main import app

        registry = AgentRegistry()
        registry.register(_make_definition(name="doomed-agent"))
        app.state.agent_registry = registry

        assert registry.get("doomed-agent") is not None

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = _auth_headers()
            resp = await client.delete(
                "/v1/agents/doomed-agent",
                headers=route_approval_headers(
                    client,
                    route_name="agents.delete",
                    operation="delete",
                    arguments={"name": "doomed-agent"},
                    details="Pytest agent delete",
                    authorization=headers["Authorization"],
                ),
            )

        assert resp.status_code == 204
        assert registry.get("doomed-agent") is None

    async def test_delete_nonexistent_agent_returns_404(self, route_approval_headers) -> None:
        from agent33.main import app

        registry = AgentRegistry()
        app.state.agent_registry = registry

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = _auth_headers()
            resp = await client.delete(
                "/v1/agents/no-such-agent",
                headers=route_approval_headers(
                    client,
                    route_name="agents.delete",
                    operation="delete",
                    arguments={"name": "no-such-agent"},
                    details="Pytest missing agent delete",
                    authorization=headers["Authorization"],
                ),
            )

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_delete_without_write_scope_returns_403(self) -> None:
        from agent33.main import app

        registry = AgentRegistry()
        registry.register(_make_definition(name="protected-agent"))
        app.state.agent_registry = registry

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete(
                "/v1/agents/protected-agent",
                headers=_auth_headers(scopes=["agents:read"]),
            )

        assert resp.status_code == 403
        # Agent should still exist
        assert registry.get("protected-agent") is not None

    async def test_delete_removes_only_target_agent(self, route_approval_headers) -> None:
        from agent33.main import app

        registry = AgentRegistry()
        registry.register(_make_definition(name="keep-me"))
        registry.register(_make_definition(name="delete-me"))
        app.state.agent_registry = registry

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            headers = _auth_headers()
            resp = await client.delete(
                "/v1/agents/delete-me",
                headers=route_approval_headers(
                    client,
                    route_name="agents.delete",
                    operation="delete",
                    arguments={"name": "delete-me"},
                    details="Pytest selective delete",
                    authorization=headers["Authorization"],
                ),
            )

        assert resp.status_code == 204
        assert registry.get("delete-me") is None
        assert registry.get("keep-me") is not None


# ---------------------------------------------------------------------------
# POST /preview-prompt — Preview system prompt
# ---------------------------------------------------------------------------


class TestPreviewPrompt:
    async def test_preview_returns_system_prompt(self) -> None:
        from agent33.main import app

        payload = _definition_payload(
            name="preview-test",
            role="researcher",
            description="A research agent for testing prompt preview",
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/agents/preview-prompt",
                json=payload,
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "system_prompt" in data
        # The prompt should contain the agent name and role
        prompt = data["system_prompt"]
        assert "preview-test" in prompt
        assert "researcher" in prompt
        assert "research agent for testing prompt preview" in prompt

    async def test_preview_with_capabilities(self) -> None:
        from agent33.main import app

        payload = _definition_payload(name="capable-agent")
        payload["capabilities"] = ["file-read", "web-search"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/agents/preview-prompt",
                json=payload,
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        prompt = resp.json()["system_prompt"]
        assert "file-read" in prompt
        assert "web-search" in prompt

    async def test_preview_invalid_definition_returns_422(self) -> None:
        from agent33.main import app

        # Missing required field 'version'
        payload = {"name": "bad", "role": "implementer"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/agents/preview-prompt",
                json=payload,
                headers=_auth_headers(),
            )

        assert resp.status_code == 422

    async def test_preview_without_read_scope_returns_403(self) -> None:
        from agent33.main import app

        payload = _definition_payload()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/agents/preview-prompt",
                json=payload,
                headers=_auth_headers(scopes=[]),
            )

        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /validate — Validate agent definition
# ---------------------------------------------------------------------------


class TestValidateDefinition:
    async def test_valid_definition_returns_valid_true(self) -> None:
        from agent33.main import app

        payload = _definition_payload(name="good-agent")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/agents/validate",
                json=payload,
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["name"] == "good-agent"
        assert data["errors"] == []

    async def test_invalid_name_returns_valid_false(self) -> None:
        from agent33.main import app

        # Name with uppercase and spaces is invalid (pattern: ^[a-z][a-z0-9-]*$)
        payload = _definition_payload()
        payload["name"] = "Bad Agent Name!"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/agents/validate",
                json=payload,
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    async def test_missing_version_returns_valid_false(self) -> None:
        from agent33.main import app

        payload = {"name": "no-version", "role": "implementer"}
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/agents/validate",
                json=payload,
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    async def test_invalid_role_returns_valid_false(self) -> None:
        from agent33.main import app

        payload = _definition_payload()
        payload["role"] = "not-a-real-role"
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/agents/validate",
                json=payload,
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    async def test_validate_requires_no_special_scope(self) -> None:
        """Validate has no require_scope dependency, so any authenticated user
        can call it (the global AuthMiddleware still requires a valid token)."""
        from agent33.main import app

        payload = _definition_payload()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Minimal scopes -- no agents:read or agents:write needed
            resp = await client.post(
                "/v1/agents/validate",
                json=payload,
                headers=_auth_headers(scopes=["some:other"]),
            )

        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    async def test_validate_with_capabilities(self) -> None:
        from agent33.main import app

        payload = _definition_payload()
        payload["capabilities"] = ["file-read", "code-execution"]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/v1/agents/validate",
                json=payload,
                headers=_auth_headers(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert data["name"] == "test-agent"
