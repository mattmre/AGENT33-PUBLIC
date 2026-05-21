"""Integration tests for the ingestion REST API (Sprint 1).

Uses ``TestClient`` against the real FastAPI app with a fresh, isolated
``IngestionService`` injected for each test via the module-level service
setter (same pattern as ``test_outcomes_api.py``).

Test plan:
  TC-A1  POST /v1/ingestion/candidates creates a CANDIDATE asset
  TC-A2  GET  /v1/ingestion/candidates/{id} returns the candidate
  TC-A3  GET  /v1/ingestion/candidates/{id} returns 404 for unknown ID
  TC-A4  POST /v1/ingestion/candidates/{id}/transition → validate succeeds
  TC-A5  POST /v1/ingestion/candidates/{id}/transition → invalid transition
           returns 422 with a CandidateTransitionError detail
  TC-A6  POST /v1/ingestion/candidates/{id}/transition → 404 on unknown ID
  TC-A7  GET  /v1/ingestion/candidates lists all assets (no filter)
  TC-A8  GET  /v1/ingestion/candidates?status=candidate filters by status
  TC-A9  GET  /v1/ingestion/candidates?tenant_id=<t> filters by tenant
  TC-A10 Auth: write endpoints reject requests without ingestion:write scope
  TC-A11 Auth: read endpoints reject requests without ingestion:read scope
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import ingestion as ingestion_mod
from agent33.ingestion.service import IngestionService
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Client / auth helpers
# ---------------------------------------------------------------------------

_TENANT = "tenant-api-test"


def _client(scopes: list[str], *, tenant_id: str = _TENANT) -> TestClient:
    token = create_access_token("ingestion-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(autouse=True)
def reset_ingestion_service() -> None:
    """Ensure each test starts with a clean, isolated IngestionService.

    Replaces the module-level service with a fresh in-memory instance and
    removes the app.state attribute so route helpers fall back to the module-
    level service.  Restored after each test.
    """
    saved_service = ingestion_mod._service
    ingestion_mod._service = IngestionService()
    had_attr = hasattr(app.state, "ingestion_service")
    saved_state = getattr(app.state, "ingestion_service", None)
    if had_attr:
        delattr(app.state, "ingestion_service")
    yield
    ingestion_mod._service = saved_service
    if had_attr:
        app.state.ingestion_service = saved_state
    elif hasattr(app.state, "ingestion_service"):
        delattr(app.state, "ingestion_service")


@pytest.fixture()
def writer_client() -> TestClient:
    return _client(["ingestion:read", "ingestion:write"])


@pytest.fixture()
def reader_client() -> TestClient:
    return _client(["ingestion:read"])


@pytest.fixture()
def no_scope_client() -> TestClient:
    return _client([])


# ---------------------------------------------------------------------------
# TC-A1: POST /v1/ingestion/candidates creates a CANDIDATE asset
# ---------------------------------------------------------------------------


class TestIngestEndpoint:
    """TC-A1: POST creates a CANDIDATE asset and returns 201."""

    def test_create_candidate_returns_201(self, writer_client: TestClient) -> None:
        resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "my-skill",
                "asset_type": "skill",
                "source_uri": "https://example.com/skill",
                "tenant_id": _TENANT,
            },
        )
        assert resp.status_code == 201

    def test_create_candidate_status_is_candidate(self, writer_client: TestClient) -> None:
        resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "my-skill",
                "asset_type": "skill",
                "source_uri": None,
                "tenant_id": _TENANT,
            },
        )
        assert resp.json()["status"] == "candidate"

    def test_create_candidate_default_confidence_is_low(self, writer_client: TestClient) -> None:
        resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "conf-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        assert resp.json()["confidence"] == "low"

    def test_create_candidate_returns_id(self, writer_client: TestClient) -> None:
        resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "id-skill", "asset_type": "tool", "tenant_id": _TENANT},
        )
        data = resp.json()
        assert "id" in data
        assert isinstance(data["id"], str)
        assert len(data["id"]) > 0

    def test_create_with_metadata(self, writer_client: TestClient) -> None:
        resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "meta-skill",
                "asset_type": "pack",
                "tenant_id": _TENANT,
                "metadata": {"version": "2.0"},
            },
        )
        assert resp.status_code == 201
        assert resp.json()["metadata"] == {"version": "2.0"}


# ---------------------------------------------------------------------------
# TC-A2 / TC-A3: GET /v1/ingestion/candidates/{id}
# ---------------------------------------------------------------------------


class TestGetEndpoint:
    """TC-A2/TC-A3: GET by ID returns the asset or 404."""

    def test_get_existing_candidate(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "get-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        reader = _client(["ingestion:read"])
        get_resp = reader.get(f"/v1/ingestion/candidates/{asset_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == asset_id
        assert get_resp.json()["name"] == "get-skill"

    def test_get_unknown_id_returns_404(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/ingestion/candidates/does-not-exist-00000")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TC-A4: Transition → validate succeeds
# ---------------------------------------------------------------------------


class TestTransitionEndpoint:
    """TC-A4: POST /transition applies lifecycle transitions correctly."""

    def test_transition_to_validated_succeeds(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "trans-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        resp = writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "validated"

    def test_transition_to_published_after_validate(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "pub-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated"},
        )
        resp = writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "published"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "published"

    def test_transition_to_revoked_with_reason(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "rev-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        resp = writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "revoked", "reason": "Rejected at intake"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"
        assert resp.json()["revocation_reason"] == "Rejected at intake"

    def test_transition_sets_validated_at_timestamp(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "ts-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        resp = writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated"},
        )
        assert resp.json()["validated_at"] is not None


# ---------------------------------------------------------------------------
# TC-A5: Invalid transition returns 422 with detail
# ---------------------------------------------------------------------------


class TestInvalidTransitionEndpoint:
    """TC-A5: An invalid transition returns 422 with a meaningful error detail."""

    def test_invalid_transition_returns_422(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "inv-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        # CANDIDATE → PUBLISHED is invalid (must go via VALIDATED)
        resp = writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "published"},
        )
        assert resp.status_code == 422

    def test_invalid_transition_error_detail_mentions_statuses(
        self, writer_client: TestClient
    ) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "err-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        resp = writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "published"},
        )
        assert resp.status_code == 422
        detail = resp.json().get("detail", "")
        # The CandidateTransitionError message contains both status names
        assert "candidate" in detail or "published" in detail

    def test_revoked_asset_cannot_be_validated(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "term-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "revoked", "reason": "terminal"},
        )
        resp = writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated"},
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# TC-A6: Transition on unknown ID returns 404
# ---------------------------------------------------------------------------


class TestTransition404:
    """TC-A6: Transition on unknown ID returns 404."""

    def test_transition_unknown_asset_returns_404(self, writer_client: TestClient) -> None:
        resp = writer_client.post(
            "/v1/ingestion/candidates/no-such-asset/transition",
            json={"target_status": "validated"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# TC-A7 / TC-A8 / TC-A9: List endpoints
# ---------------------------------------------------------------------------


class TestListEndpoint:
    """TC-A7/TC-A8/TC-A9: GET /candidates list endpoints."""

    def test_list_all_returns_created_assets(self, writer_client: TestClient) -> None:
        writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "list-a", "asset_type": "skill", "tenant_id": _TENANT},
        )
        writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "list-b", "asset_type": "skill", "tenant_id": _TENANT},
        )
        resp = _client(["ingestion:read"]).get("/v1/ingestion/candidates")
        assert resp.status_code == 200
        names = [a["name"] for a in resp.json()]
        assert "list-a" in names
        assert "list-b" in names

    def test_list_by_status_filters_correctly(self, writer_client: TestClient) -> None:
        # Create two candidates, validate one
        r1 = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "status-a", "asset_type": "skill", "tenant_id": _TENANT},
        )
        r2 = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "status-b", "asset_type": "skill", "tenant_id": _TENANT},
        )
        a1_id = r1.json()["id"]
        writer_client.post(
            f"/v1/ingestion/candidates/{a1_id}/transition",
            json={"target_status": "validated"},
        )
        reader = _client(["ingestion:read"])
        cands = reader.get("/v1/ingestion/candidates?status=candidate").json()
        validated = reader.get("/v1/ingestion/candidates?status=validated").json()
        cand_ids = [a["id"] for a in cands]
        validated_ids = [a["id"] for a in validated]
        assert r2.json()["id"] in cand_ids
        assert a1_id in validated_ids
        assert a1_id not in cand_ids

    def test_list_by_tenant_filters_correctly(self, writer_client: TestClient) -> None:
        other_tenant = "other-tenant-999"
        writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "my-asset", "asset_type": "skill", "tenant_id": _TENANT},
        )
        writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "other-asset", "asset_type": "skill", "tenant_id": other_tenant},
        )
        reader = _client(["ingestion:read"])
        resp = reader.get(f"/v1/ingestion/candidates?tenant_id={_TENANT}")
        assert resp.status_code == 200
        names = [a["name"] for a in resp.json()]
        assert "my-asset" in names
        assert "other-asset" not in names


# ---------------------------------------------------------------------------
# TC-A10 / TC-A11: Auth scope enforcement
# ---------------------------------------------------------------------------


class TestAuthEnforcement:
    """TC-A10/TC-A11: Endpoints enforce required scopes."""

    def test_post_without_write_scope_returns_403(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.post(
            "/v1/ingestion/candidates",
            json={"name": "unauth", "asset_type": "skill", "tenant_id": _TENANT},
        )
        assert resp.status_code in (401, 403)

    def test_get_without_read_scope_returns_403(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.get("/v1/ingestion/candidates/some-id")
        assert resp.status_code in (401, 403)

    def test_transition_without_write_scope_returns_403(self, no_scope_client: TestClient) -> None:
        resp = no_scope_client.post(
            "/v1/ingestion/candidates/some-id/transition",
            json={"target_status": "validated"},
        )
        assert resp.status_code in (401, 403)

    def test_reader_cannot_post_candidate(self, reader_client: TestClient) -> None:
        resp = reader_client.post(
            "/v1/ingestion/candidates",
            json={"name": "reader-post", "asset_type": "skill", "tenant_id": _TENANT},
        )
        assert resp.status_code in (401, 403)
