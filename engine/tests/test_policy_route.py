"""Tests for GET /v1/policy/active."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.security.policy import ActivePolicy, get_active_policy

# ---------------------------------------------------------------------------
# Unit tests — policy model
# ---------------------------------------------------------------------------


def test_tool_use_mode_override() -> None:
    """get_active_policy() returns settings values when attributes are present."""
    from agent33.security.policy import get_active_policy

    class OverrideSettings:
        tool_use_mode = "dry-run"
        evidence_required = False
        review_authority = "automation"

    policy = get_active_policy(OverrideSettings())
    assert policy.tool_use_mode == "dry-run"
    assert policy.evidence_required is False
    assert policy.review_authority == "automation"


def test_get_active_policy_returns_active_policy_model() -> None:
    """get_active_policy() returns an ActivePolicy with expected defaults."""

    class _FakeSettings:
        pass

    policy = get_active_policy(_FakeSettings())

    assert isinstance(policy, ActivePolicy)
    assert policy.tool_use_mode == "audit"
    assert policy.evidence_required is True
    assert policy.review_authority == "user"


def test_policy_shards_present() -> None:
    """Policy response contains at least one policy shard."""

    class _FakeSettings:
        pass

    policy = get_active_policy(_FakeSettings())

    assert len(policy.policy_shards) >= 1
    ids = {shard.id for shard in policy.policy_shards}
    assert "policy.tool-use.default" in ids


def test_collaboration_modes_present() -> None:
    """Policy response contains collaboration modes."""

    class _FakeSettings:
        pass

    policy = get_active_policy(_FakeSettings())

    assert len(policy.collaboration_modes) >= 1
    ids = {mode.id for mode in policy.collaboration_modes}
    assert "paired" in ids
    assert "autonomous" in ids


# ---------------------------------------------------------------------------
# Integration tests — route layer
# ---------------------------------------------------------------------------


def test_get_active_policy_returns_200() -> None:
    """GET /v1/policy/active returns 200 with a valid token."""
    token = create_access_token("test-user", scopes=["agents:read"], tenant_id="tenant-test")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.get("/v1/policy/active")

    assert response.status_code == 200
    data = response.json()
    assert "policy_shards" in data
    assert "collaboration_modes" in data
    assert isinstance(data["policy_shards"], list)
    assert len(data["policy_shards"]) >= 1


def test_get_active_policy_requires_read_scope_401() -> None:
    """GET /v1/policy/active returns 401 when no auth token is provided."""
    client = TestClient(app)

    response = client.get("/v1/policy/active")

    assert response.status_code == 401


def test_get_active_policy_requires_read_scope_403() -> None:
    """GET /v1/policy/active returns 403 when token lacks agents:read scope."""
    token = create_access_token("test-user", scopes=["workflows:read"], tenant_id="tenant-test")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.get("/v1/policy/active")

    assert response.status_code == 403


def test_get_active_policy_response_shape() -> None:
    """Response contains the correct field names and types."""
    token = create_access_token("test-user", scopes=["agents:read"], tenant_id="tenant-test")
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

    response = client.get("/v1/policy/active")

    assert response.status_code == 200
    data = response.json()

    # Top-level fields
    assert "tool_use_mode" in data
    assert "evidence_required" in data
    assert "review_authority" in data
    assert "policy_shards" in data
    assert "collaboration_modes" in data

    # Shard shape
    shard = data["policy_shards"][0]
    assert "id" in shard
    assert "label" in shard
    assert "mode" in shard

    # Collaboration mode shape
    mode = data["collaboration_modes"][0]
    assert "id" in mode
    assert "label" in mode
    assert "detail" in mode
