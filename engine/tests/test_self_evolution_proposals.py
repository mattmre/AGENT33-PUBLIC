"""Tests for Gate 3.1 self-evolution proposal endpoints.

Covers:
- GET /v1/improvements/proposals
- POST /v1/improvements/proposals/generate
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent33.config import settings
from agent33.improvement.models import LearningSignalSeverity, LearningSignalType
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_route_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset improvement singletons and configure memory backend before each test."""
    from agent33.api.routes.improvements import _reset_service

    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "memory")
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_tuning_loop_enabled", True)
    monkeypatch.setattr(settings, "improvement_tuning_loop_dry_run", True)
    monkeypatch.setattr(settings, "improvement_tuning_loop_require_approval", False)
    _reset_service()


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    token = create_access_token(
        subject="test-user",
        tenant_id="default",
        scopes=["admin"],
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _seed_signals_via_api(
    client: TestClient,
    headers: dict[str, str],
    count: int = 15,
) -> None:
    """Seed enough learning signals so the tuning loop has a valid sample."""
    for i in range(count):
        client.post(
            "/v1/improvements/learning/signals",
            json={
                "signal_type": LearningSignalType.FEEDBACK,
                "severity": LearningSignalSeverity.HIGH,
                "summary": (
                    f"Detailed recurring signal from the release pipeline with evidence bundle {i}"
                ),
                "details": (
                    "Observed across canary and stable lanes with reproducible "
                    f"steps for sample {i}"
                ),
                "source": "test-api",
                "tenant_id": "default",
                "quality_score": 0.9,
                "context": {"pipeline": "release", "sample": str(i)},
            },
            headers=headers,
        )


# ---------------------------------------------------------------------------
# GET /v1/improvements/proposals
# ---------------------------------------------------------------------------


class TestListProposals:
    def test_list_proposals_returns_200_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Empty tuning history returns 200 with empty proposals list."""
        resp = client.get("/v1/improvements/proposals", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "proposals" in body
        assert "count" in body
        assert "type" in body
        assert body["count"] == 0
        assert body["type"] == "tuning-calibration"
        assert body["proposals"] == []

    def test_list_proposals_returns_real_cycle_records(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """After a tuning cycle runs, list_proposals returns the cycle data."""
        _seed_signals_via_api(client, auth_headers, count=15)
        # Run a cycle so there's history
        run_resp = client.post("/v1/improvements/tuning/run", headers=auth_headers)
        assert run_resp.status_code == 200

        resp = client.get("/v1/improvements/proposals", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()

        assert body["count"] >= 1
        proposal = body["proposals"][0]
        assert "id" in proposal
        assert "status" in proposal
        assert "proposal_type" in proposal
        assert proposal["proposal_type"] == "config-calibration"
        assert "summary" in proposal
        assert "created_at" in proposal
        assert "completed_at" in proposal
        assert "sample_size" in proposal
        assert "before_values" in proposal
        assert "after_values" in proposal
        assert "deltas" in proposal

    def test_list_proposals_status_filter(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """status query parameter filters proposals by outcome."""
        _seed_signals_via_api(client, auth_headers, count=15)
        client.post("/v1/improvements/tuning/run", headers=auth_headers)

        resp_all = client.get("/v1/improvements/proposals", headers=auth_headers)
        assert resp_all.status_code == 200
        total_count = resp_all.json()["count"]

        # Filter by an outcome that doesn't exist yet
        resp_filtered = client.get(
            "/v1/improvements/proposals?status=pending_approval", headers=auth_headers
        )
        assert resp_filtered.status_code == 200
        # All returned proposals must match the filter
        body = resp_filtered.json()
        for p in body["proposals"]:
            assert p["status"] == "pending_approval"
        # Filtered count <= total
        assert body["count"] <= total_count

    def test_list_proposals_limit_parameter(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """limit parameter caps the number of returned proposals."""
        _seed_signals_via_api(client, auth_headers, count=15)
        # Run multiple cycles
        for _ in range(3):
            client.post("/v1/improvements/tuning/run", headers=auth_headers)

        resp = client.get("/v1/improvements/proposals?limit=2", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] <= 2
        assert len(body["proposals"]) <= 2

    def test_list_proposals_requires_auth(self, client: TestClient) -> None:
        """Request without auth token gets 401 or 403."""
        resp = client.get("/v1/improvements/proposals")
        assert resp.status_code in {401, 403}


# ---------------------------------------------------------------------------
# POST /v1/improvements/proposals/generate
# ---------------------------------------------------------------------------


class TestGenerateProposal:
    def test_generate_proposal_triggers_tuning_sandbox(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """generate route runs the proposal sandbox and returns the record."""
        monkeypatch.setattr(settings, "self_improve_proposal_sandbox_enabled", True)
        _seed_signals_via_api(client, auth_headers, count=15)

        resp = client.post("/v1/improvements/proposals/generate", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Must be a TuningProposalSandboxRecord
        assert body["outcome"] == "proposal_only"
        assert body["mutation_allowed"] is False
        assert body["approval_allowed"] is False
        assert body["production_mutation_attempted"] is False
        assert body["promotion_required"] is True
        assert "proposed_config_changes" in body
        assert "cycle_id" in body
        assert "sample_size" in body

    def test_generate_proposal_appears_in_list(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After generating a proposal, it appears in GET /proposals."""
        monkeypatch.setattr(settings, "self_improve_proposal_sandbox_enabled", True)
        _seed_signals_via_api(client, auth_headers, count=15)

        gen_resp = client.post("/v1/improvements/proposals/generate", headers=auth_headers)
        assert gen_resp.status_code == 200
        generated_id = gen_resp.json()["cycle_id"]

        list_resp = client.get("/v1/improvements/proposals", headers=auth_headers)
        assert list_resp.status_code == 200
        ids = [p["id"] for p in list_resp.json()["proposals"]]
        assert generated_id in ids

    def test_generate_proposal_disabled_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When sandbox feature flag is off, generate returns 404."""
        monkeypatch.setattr(settings, "self_improve_proposal_sandbox_enabled", False)

        resp = client.post("/v1/improvements/proposals/generate", headers=auth_headers)
        assert resp.status_code == 404

    def test_generate_proposal_requires_auth(self, client: TestClient) -> None:
        """Request without auth token gets 401 or 403."""
        resp = client.post("/v1/improvements/proposals/generate")
        assert resp.status_code in {401, 403}

    def test_generate_proposal_learning_disabled_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When learning is disabled, generate returns 404 (from _ensure_learning_enabled)."""
        monkeypatch.setattr(settings, "improvement_learning_enabled", False)
        from agent33.api.routes.improvements import _reset_service

        _reset_service()

        resp = client.post("/v1/improvements/proposals/generate", headers=auth_headers)
        assert resp.status_code == 404
