"""Tests for T9: lifecycle journal and operator review queue.

Test plan:
  TJ-1   journal.record() writes an entry retrievable via entries_for()
  TJ-2   entries_for() returns entries in ascending occurred_at order
  TJ-3   entries_for_tenant() respects the limit parameter
  TJ-4   validate() with journal wired creates a journal entry with correct
           from_status=candidate / to_status=validated
  TJ-5   promote() with journal creates a journal entry with correct
           from_status=validated / to_status=published
  TJ-6   revoke() with journal creates a journal entry with correct to_status=revoked
  TJ-7   list_pending_review() returns only CANDIDATE assets with review_required=True
  TJ-8   approve() clears review_required flag and advances to VALIDATED
  TJ-9   reject() revokes the asset
  TJ-10  get_journal() returns [] when no journal is wired
  TJ-11  get_tenant_journal() returns [] when no journal is wired
  TJ-12  cleanup_expired() removes expired persisted journal entries
  API-1  GET /v1/ingestion/candidates/{id}/journal returns correct shape
  API-2  GET /v1/ingestion/journal returns a list
  API-3  GET /v1/ingestion/review-queue returns only pending-review assets
  API-4  POST /v1/ingestion/review-queue/{id}/approve returns approved asset
  API-5  POST /v1/ingestion/review-queue/{id}/reject returns revoked asset
  API-6  GET /v1/ingestion/candidates/{id}/journal returns 404 for unknown asset
  API-7  approve on non-existent asset returns 404
  API-8  reject on non-existent asset returns 404
  API-9  review-queue approve/reject require ingestion:write scope
  API-10 GET /v1/ingestion/journal accepts an additive limit query parameter
"""

from __future__ import annotations

from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import ingestion as ingestion_mod
from agent33.ingestion.journal import TransitionJournal
from agent33.ingestion.models import CandidateAsset, CandidateStatus, ConfidenceLevel
from agent33.ingestion.service import IngestionService
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Helpers and shared fixtures
# ---------------------------------------------------------------------------

_TENANT = "tenant-journal-test"


def _make_asset(
    *,
    tenant_id: str = _TENANT,
    status: CandidateStatus = CandidateStatus.CANDIDATE,
    metadata: dict | None = None,
) -> CandidateAsset:
    """Create a CandidateAsset via IngestionService and return it."""
    import uuid
    from datetime import UTC, datetime

    return CandidateAsset(
        id=str(uuid.uuid4()),
        name="test-asset",
        asset_type="skill",
        status=status,
        confidence=ConfidenceLevel.LOW,
        tenant_id=tenant_id,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# TJ-1..TJ-3: TransitionJournal unit tests
# ---------------------------------------------------------------------------


class TestTransitionJournalRecordAndQuery:
    """TJ-1: record() writes an entry; entries_for() retrieves it."""

    def test_record_and_retrieve_entry(self, tmp_path) -> None:
        journal = TransitionJournal(str(tmp_path / "j.db"))
        asset = _make_asset()
        journal.record(
            asset,
            CandidateStatus.CANDIDATE,
            operator="op-alice",
            reason="test validate",
        )
        entries = journal.entries_for(asset.id)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["asset_id"] == asset.id
        assert entry["tenant_id"] == _TENANT
        assert entry["from_status"] == "candidate"
        assert entry["to_status"] == "candidate"  # asset.status was not changed
        assert entry["event_type"] == "transition"
        assert entry["operator"] == "op-alice"
        assert entry["reason"] == "test validate"
        assert entry["details"] == {}
        assert "occurred_at" in entry
        journal.close()

    def test_entries_for_unknown_asset_returns_empty(self, tmp_path) -> None:
        journal = TransitionJournal(str(tmp_path / "j.db"))
        assert journal.entries_for("no-such-id") == []
        journal.close()

    def test_multiple_entries_different_assets_isolated(self, tmp_path) -> None:
        journal = TransitionJournal(str(tmp_path / "j.db"))
        a1 = _make_asset()
        a2 = _make_asset()
        journal.record(a1, CandidateStatus.CANDIDATE, operator="op", reason="r1")
        journal.record(a2, CandidateStatus.CANDIDATE, operator="op", reason="r2")
        assert len(journal.entries_for(a1.id)) == 1
        assert len(journal.entries_for(a2.id)) == 1
        journal.close()


class TestTransitionJournalOrdering:
    """TJ-2: entries_for() returns entries in ascending occurred_at order."""

    def test_entries_for_ascending_order(self, tmp_path) -> None:
        import time

        journal = TransitionJournal(str(tmp_path / "j.db"))
        asset = _make_asset()
        journal.record(asset, CandidateStatus.CANDIDATE, operator="op", reason="first")
        time.sleep(0.01)
        journal.record(asset, CandidateStatus.VALIDATED, operator="op", reason="second")
        entries = journal.entries_for(asset.id)
        assert len(entries) == 2
        assert entries[0]["reason"] == "first"
        assert entries[1]["reason"] == "second"
        assert entries[0]["occurred_at"] <= entries[1]["occurred_at"]
        journal.close()


class TestTransitionJournalTenantLimit:
    """TJ-3: entries_for_tenant() respects the limit parameter."""

    def test_tenant_limit_respected(self, tmp_path) -> None:
        journal = TransitionJournal(str(tmp_path / "j.db"))
        asset = _make_asset()
        for i in range(10):
            journal.record(asset, CandidateStatus.CANDIDATE, operator="op", reason=f"r{i}")
        entries = journal.entries_for_tenant(_TENANT, limit=3)
        assert len(entries) == 3
        journal.close()

    def test_tenant_entries_descending_order(self, tmp_path) -> None:
        import time

        journal = TransitionJournal(str(tmp_path / "j.db"))
        asset = _make_asset()
        for i in range(3):
            journal.record(asset, CandidateStatus.CANDIDATE, operator="op", reason=f"r{i}")
            time.sleep(0.01)
        entries = journal.entries_for_tenant(_TENANT, limit=10)
        # Descending: most recent first
        assert entries[0]["occurred_at"] >= entries[-1]["occurred_at"]
        journal.close()

    def test_tenant_filter_by_tenant(self, tmp_path) -> None:
        journal = TransitionJournal(str(tmp_path / "j.db"))
        a1 = _make_asset(tenant_id="tenant-A")
        a2 = _make_asset(tenant_id="tenant-B")
        journal.record(a1, CandidateStatus.CANDIDATE, operator="op", reason="for-A")
        journal.record(a2, CandidateStatus.CANDIDATE, operator="op", reason="for-B")
        entries_a = journal.entries_for_tenant("tenant-A")
        entries_b = journal.entries_for_tenant("tenant-B")
        assert all(e["tenant_id"] == "tenant-A" for e in entries_a)
        assert all(e["tenant_id"] == "tenant-B" for e in entries_b)
        journal.close()

    def test_cleanup_expired_removes_old_entries(self, tmp_path) -> None:
        import sqlite3
        from datetime import UTC, datetime, timedelta

        db_path = tmp_path / "j.db"
        with closing(TransitionJournal(db_path, retention_days=30)) as journal:
            stale_asset = _make_asset()
            recent_asset = _make_asset()
            journal.record(stale_asset, CandidateStatus.CANDIDATE, operator="op", reason="stale")
            journal.record(recent_asset, CandidateStatus.CANDIDATE, operator="op", reason="recent")

        stale_occurred_at = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE ingestion_journal SET occurred_at = ? WHERE asset_id = ?",
                (stale_occurred_at, stale_asset.id),
            )
            conn.commit()

        with closing(TransitionJournal(db_path, retention_days=30)) as journal:
            deleted = journal.cleanup_expired()
            assert deleted == 1
            assert journal.entries_for(stale_asset.id) == []
            tenant_entries = journal.entries_for_tenant(_TENANT, limit=10)
            assert [entry["reason"] for entry in tenant_entries] == ["recent"]


# ---------------------------------------------------------------------------
# TJ-4..TJ-6: IngestionService + journal integration
# ---------------------------------------------------------------------------


class TestServiceJournalIntegration:
    """TJ-4/TJ-5/TJ-6: service.validate/promote/revoke write journal entries."""

    @pytest.fixture()
    def svc_with_journal(self, tmp_path):
        journal = TransitionJournal(str(tmp_path / "j.db"))
        svc = IngestionService(journal=journal)
        yield svc, journal
        journal.close()

    def test_validate_writes_journal_entry(self, svc_with_journal) -> None:
        svc, journal = svc_with_journal
        asset = svc.ingest(
            name="skill-a",
            asset_type="skill",
            source_uri=None,
            tenant_id=_TENANT,
        )
        svc.validate(asset.id, operator="op-validate", reason="manual review passed")
        entries = journal.entries_for(asset.id)
        assert len(entries) == 2
        e = entries[-1]
        assert e["from_status"] == "candidate"
        assert e["to_status"] == "validated"
        assert e["event_type"] == "transition"
        assert e["operator"] == "op-validate"
        assert e["reason"] == "manual review passed"

    def test_promote_writes_journal_entry(self, svc_with_journal) -> None:
        svc, journal = svc_with_journal
        asset = svc.ingest(
            name="skill-b",
            asset_type="skill",
            source_uri=None,
            tenant_id=_TENANT,
        )
        svc.validate(asset.id, operator="op", reason="validated")
        svc.promote(asset.id, operator="op-promote", reason="promoting to prod")
        entries = journal.entries_for(asset.id)
        assert len(entries) == 3
        promote_entry = entries[-1]
        assert promote_entry["from_status"] == "validated"
        assert promote_entry["to_status"] == "published"
        assert promote_entry["event_type"] == "transition"
        assert promote_entry["operator"] == "op-promote"
        assert promote_entry["reason"] == "promoting to prod"

    def test_revoke_writes_journal_entry(self, svc_with_journal) -> None:
        svc, journal = svc_with_journal
        asset = svc.ingest(
            name="skill-c",
            asset_type="skill",
            source_uri=None,
            tenant_id=_TENANT,
        )
        svc.revoke(asset.id, reason="policy violation", operator="op-revoke")
        entries = journal.entries_for(asset.id)
        assert len(entries) == 2
        e = entries[-1]
        assert e["from_status"] == "candidate"
        assert e["to_status"] == "revoked"
        assert e["event_type"] == "transition"
        assert e["operator"] == "op-revoke"
        assert e["reason"] == "policy violation"


# ---------------------------------------------------------------------------
# TJ-7..TJ-9: Operator review queue
# ---------------------------------------------------------------------------


class TestOperatorReviewQueue:
    """TJ-7/TJ-8/TJ-9: list_pending_review / approve / reject."""

    def test_list_pending_review_returns_only_review_required_candidates(self) -> None:
        svc = IngestionService()
        # Create candidate with review_required=True
        a = svc.ingest(name="review-me", asset_type="skill", source_uri=None, tenant_id=_TENANT)
        svc.patch_metadata(a.id, {"review_required": True})
        # Create candidate without the flag
        b = svc.ingest(name="no-review", asset_type="skill", source_uri=None, tenant_id=_TENANT)
        # Create asset with review_required but validated (wrong status)
        c = svc.ingest(
            name="validated-review", asset_type="skill", source_uri=None, tenant_id=_TENANT
        )
        svc.patch_metadata(c.id, {"review_required": True})
        svc.validate(c.id, operator="op", reason="auto")

        pending = svc.list_pending_review(_TENANT)
        pending_ids = [p.id for p in pending]
        assert a.id in pending_ids
        assert b.id not in pending_ids
        assert c.id not in pending_ids

    def test_list_pending_review_empty_when_none(self) -> None:
        svc = IngestionService()
        result = svc.list_pending_review(_TENANT)
        assert result == []

    def test_approve_advances_to_validated(self) -> None:
        svc = IngestionService()
        asset = svc.ingest(
            name="approve-me", asset_type="skill", source_uri=None, tenant_id=_TENANT
        )
        svc.patch_metadata(asset.id, {"review_required": True, "quarantine": True})
        updated = svc.approve(asset.id, operator="op-approve", reason="looks good")
        assert updated.status == CandidateStatus.VALIDATED

    def test_approve_clears_review_required_flag(self) -> None:
        svc = IngestionService()
        asset = svc.ingest(
            name="clear-flag", asset_type="skill", source_uri=None, tenant_id=_TENANT
        )
        svc.patch_metadata(asset.id, {"review_required": True, "quarantine": True})
        updated = svc.approve(asset.id, operator="op", reason="ok")
        assert updated.metadata.get("review_required") is False
        assert updated.metadata.get("quarantine") is False

    def test_reject_revokes_asset(self) -> None:
        svc = IngestionService()
        asset = svc.ingest(
            name="reject-me", asset_type="skill", source_uri=None, tenant_id=_TENANT
        )
        svc.patch_metadata(asset.id, {"review_required": True})
        rejected = svc.reject(asset.id, operator="op-reject", reason="policy violation")
        assert rejected.status == CandidateStatus.REVOKED

    def test_reject_sets_revocation_reason(self) -> None:
        svc = IngestionService()
        asset = svc.ingest(
            name="reason-me", asset_type="skill", source_uri=None, tenant_id=_TENANT
        )
        rejected = svc.reject(asset.id, operator="op", reason="bad content")
        assert rejected.revocation_reason == "bad content"


# ---------------------------------------------------------------------------
# TJ-10/TJ-11: get_journal / get_tenant_journal without journal wired
# ---------------------------------------------------------------------------


class TestServiceWithoutJournal:
    """TJ-10/TJ-11: service methods return [] when no journal is wired."""

    def test_get_journal_returns_empty_without_journal(self) -> None:
        svc = IngestionService()
        result = svc.get_journal("any-id")
        assert result == []

    def test_get_tenant_journal_returns_empty_without_journal(self) -> None:
        svc = IngestionService()
        result = svc.get_tenant_journal(_TENANT)
        assert result == []


# ---------------------------------------------------------------------------
# API tests — client setup (mirrors test_ingestion_api.py pattern)
# ---------------------------------------------------------------------------


def _client(scopes: list[str], *, tenant_id: str = _TENANT) -> TestClient:
    token = create_access_token("ingestion-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(autouse=True)
def reset_ingestion_service(tmp_path) -> None:
    """Isolate each test with a fresh IngestionService that has a real journal."""
    journal = TransitionJournal(str(tmp_path / "test_journal.db"))
    fresh_svc = IngestionService(journal=journal)
    saved_service = ingestion_mod._service
    ingestion_mod._service = fresh_svc
    had_attr = hasattr(app.state, "ingestion_service")
    saved_state = getattr(app.state, "ingestion_service", None)
    if had_attr:
        delattr(app.state, "ingestion_service")
    yield
    journal.close()
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


# ---------------------------------------------------------------------------
# API-1: GET /v1/ingestion/candidates/{id}/journal
# ---------------------------------------------------------------------------


class TestAssetJournalEndpoint:
    """API-1: GET /v1/ingestion/candidates/{id}/journal returns correct shape."""

    def test_journal_includes_ingested_event_for_new_asset(
        self, writer_client: TestClient
    ) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "j-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        resp = writer_client.get(f"/v1/ingestion/candidates/{asset_id}/journal")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["event_type"] == "ingested"

    def test_journal_has_entry_after_transition(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "j-trans", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated", "operator": "op-api"},
        )
        resp = writer_client.get(f"/v1/ingestion/candidates/{asset_id}/journal")
        assert resp.status_code == 200
        entries = resp.json()
        transition_entry = next(entry for entry in entries if entry["event_type"] == "transition")
        assert transition_entry["from_status"] == "candidate"
        assert transition_entry["to_status"] == "validated"
        assert transition_entry["asset_id"] == asset_id
        assert "occurred_at" in transition_entry

    def test_journal_entries_have_required_fields(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "fields-skill", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated"},
        )
        entries = writer_client.get(f"/v1/ingestion/candidates/{asset_id}/journal").json()
        assert len(entries) >= 1
        entry = entries[0]
        for field in (
            "asset_id",
            "tenant_id",
            "from_status",
            "to_status",
            "event_type",
            "operator",
            "reason",
            "details",
            "occurred_at",
        ):
            assert field in entry, f"Missing field: {field}"


class TestAssetJournal404:
    """API-6: GET journal for unknown asset returns 404."""

    def test_journal_404_for_unknown_asset(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/ingestion/candidates/no-such-asset-xxx/journal")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API-2: GET /v1/ingestion/journal
# ---------------------------------------------------------------------------


class TestTenantJournalEndpoint:
    """API-2: GET /v1/ingestion/journal returns a list."""

    def test_tenant_journal_returns_list(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/ingestion/journal")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_tenant_journal_contains_entry_after_transition(
        self, writer_client: TestClient
    ) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "tenant-j", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated"},
        )
        resp = writer_client.get("/v1/ingestion/journal")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    def test_tenant_journal_limit_query_param(self, writer_client: TestClient) -> None:
        create_resp = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "tenant-limit", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = create_resp.json()["id"]
        writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated", "operator": "op-limit"},
        )
        writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={
                "target_status": "revoked",
                "operator": "op-limit",
                "reason": "limit-test",
            },
        )

        resp = writer_client.get("/v1/ingestion/journal?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["to_status"] == "revoked"


# ---------------------------------------------------------------------------
# API-3: GET /v1/ingestion/review-queue
# ---------------------------------------------------------------------------


class TestReviewQueueEndpoint:
    """API-3: GET /v1/ingestion/review-queue returns pending-review assets only."""

    def test_review_queue_empty_initially(self, reader_client: TestClient) -> None:
        resp = reader_client.get("/v1/ingestion/review-queue")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_review_queue_contains_only_pending_review_candidates(
        self, writer_client: TestClient
    ) -> None:
        # Create a candidate with review_required metadata
        r1 = writer_client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "review-me",
                "asset_type": "skill",
                "tenant_id": _TENANT,
                "metadata": {"review_required": True},
            },
        )
        # Create a candidate without review_required
        r2 = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "no-review", "asset_type": "skill", "tenant_id": _TENANT},
        )
        resp = writer_client.get("/v1/ingestion/review-queue")
        assert resp.status_code == 200
        pending_ids = [a["id"] for a in resp.json()]
        assert r1.json()["id"] in pending_ids
        assert r2.json()["id"] not in pending_ids

    def test_validated_asset_not_in_review_queue(self, writer_client: TestClient) -> None:
        r = writer_client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "will-validate",
                "asset_type": "skill",
                "tenant_id": _TENANT,
                "metadata": {"review_required": True},
            },
        )
        asset_id = r.json()["id"]
        writer_client.post(
            f"/v1/ingestion/candidates/{asset_id}/transition",
            json={"target_status": "validated"},
        )
        resp = writer_client.get("/v1/ingestion/review-queue")
        pending_ids = [a["id"] for a in resp.json()]
        assert asset_id not in pending_ids


# ---------------------------------------------------------------------------
# API-4: POST /v1/ingestion/review-queue/{id}/approve
# ---------------------------------------------------------------------------


class TestApproveEndpoint:
    """API-4: POST /review-queue/{id}/approve returns approved asset."""

    def test_approve_returns_validated_asset(self, writer_client: TestClient) -> None:
        r = writer_client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "approve-api",
                "asset_type": "skill",
                "tenant_id": _TENANT,
                "metadata": {"review_required": True},
            },
        )
        asset_id = r.json()["id"]
        resp = writer_client.post(
            f"/v1/ingestion/review-queue/{asset_id}/approve",
            json={"operator": "op-api", "reason": "looks great"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "validated"

    def test_approve_clears_review_required_in_response(self, writer_client: TestClient) -> None:
        r = writer_client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "flag-clear",
                "asset_type": "skill",
                "tenant_id": _TENANT,
                "metadata": {"review_required": True, "quarantine": True},
            },
        )
        asset_id = r.json()["id"]
        resp = writer_client.post(
            f"/v1/ingestion/review-queue/{asset_id}/approve",
            json={"operator": "op", "reason": "ok"},
        )
        assert resp.status_code == 200
        metadata = resp.json()["metadata"]
        assert metadata.get("review_required") is False
        assert metadata.get("quarantine") is False

    def test_approve_adds_journal_entry(self, writer_client: TestClient) -> None:
        r = writer_client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "journal-approve",
                "asset_type": "skill",
                "tenant_id": _TENANT,
                "metadata": {"review_required": True},
            },
        )
        asset_id = r.json()["id"]
        writer_client.post(
            f"/v1/ingestion/review-queue/{asset_id}/approve",
            json={"operator": "op-journal", "reason": "journaled approval"},
        )
        journal_resp = writer_client.get(f"/v1/ingestion/candidates/{asset_id}/journal")
        assert journal_resp.status_code == 200
        entries = journal_resp.json()
        assert any(e["to_status"] == "validated" for e in entries)


class TestApprove404:
    """API-7: approve on non-existent asset returns 404."""

    def test_approve_unknown_asset_returns_404(self, writer_client: TestClient) -> None:
        resp = writer_client.post(
            "/v1/ingestion/review-queue/no-such-asset-xxx/approve",
            json={"operator": "op", "reason": "r"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API-5: POST /v1/ingestion/review-queue/{id}/reject
# ---------------------------------------------------------------------------


class TestRejectEndpoint:
    """API-5: POST /review-queue/{id}/reject returns revoked asset."""

    def test_reject_returns_revoked_asset(self, writer_client: TestClient) -> None:
        r = writer_client.post(
            "/v1/ingestion/candidates",
            json={
                "name": "reject-api",
                "asset_type": "skill",
                "tenant_id": _TENANT,
                "metadata": {"review_required": True},
            },
        )
        asset_id = r.json()["id"]
        resp = writer_client.post(
            f"/v1/ingestion/review-queue/{asset_id}/reject",
            json={"operator": "op-api", "reason": "policy violation"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "revoked"

    def test_reject_sets_revocation_reason(self, writer_client: TestClient) -> None:
        r = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "rev-reason", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = r.json()["id"]
        resp = writer_client.post(
            f"/v1/ingestion/review-queue/{asset_id}/reject",
            json={"operator": "op", "reason": "dangerous content"},
        )
        assert resp.status_code == 200
        assert resp.json()["revocation_reason"] == "dangerous content"

    def test_reject_adds_journal_entry(self, writer_client: TestClient) -> None:
        r = writer_client.post(
            "/v1/ingestion/candidates",
            json={"name": "journal-reject", "asset_type": "skill", "tenant_id": _TENANT},
        )
        asset_id = r.json()["id"]
        writer_client.post(
            f"/v1/ingestion/review-queue/{asset_id}/reject",
            json={"operator": "op-journal", "reason": "rejected"},
        )
        journal_resp = writer_client.get(f"/v1/ingestion/candidates/{asset_id}/journal")
        assert journal_resp.status_code == 200
        entries = journal_resp.json()
        assert any(e["to_status"] == "revoked" for e in entries)


class TestReject404:
    """API-8: reject on non-existent asset returns 404."""

    def test_reject_unknown_asset_returns_404(self, writer_client: TestClient) -> None:
        resp = writer_client.post(
            "/v1/ingestion/review-queue/no-such-asset-xxx/reject",
            json={"operator": "op", "reason": "r"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API-9: Scope enforcement on review-queue endpoints
# ---------------------------------------------------------------------------


class TestReviewQueueScopeEnforcement:
    """API-9: approve/reject require ingestion:write; review-queue read requires ingestion:read."""

    def test_approve_requires_write_scope(self) -> None:
        reader = _client(["ingestion:read"])
        resp = reader.post(
            "/v1/ingestion/review-queue/any-id/approve",
            json={"operator": "op", "reason": "r"},
        )
        assert resp.status_code in (401, 403)

    def test_reject_requires_write_scope(self) -> None:
        reader = _client(["ingestion:read"])
        resp = reader.post(
            "/v1/ingestion/review-queue/any-id/reject",
            json={"operator": "op", "reason": "r"},
        )
        assert resp.status_code in (401, 403)

    def test_review_queue_list_requires_read_scope(self) -> None:
        no_scope = _client([])
        resp = no_scope.get("/v1/ingestion/review-queue")
        assert resp.status_code in (401, 403)

    def test_asset_journal_requires_read_scope(self) -> None:
        no_scope = _client([])
        resp = no_scope.get("/v1/ingestion/candidates/any-id/journal")
        assert resp.status_code in (401, 403)

    def test_tenant_journal_requires_read_scope(self) -> None:
        no_scope = _client([])
        resp = no_scope.get("/v1/ingestion/journal")
        assert resp.status_code in (401, 403)
