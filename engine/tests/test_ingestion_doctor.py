"""Tests for the detect-only SkillsDoctor diagnostics module.

Covers:
- Unit-level diagnose_asset() for all individual check paths
- diagnose_tenant() aggregate counting
- summary_report() healthy-asset exclusion
- API endpoints: GET /doctor/{asset_id}, GET /doctor, GET /doctor/report
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import ingestion as ingestion_mod
from agent33.ingestion.doctor import SkillsDoctor
from agent33.ingestion.models import CandidateAsset, CandidateStatus, ConfidenceLevel  # noqa: F401
from agent33.ingestion.service import IngestionService
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_asset(
    *,
    asset_id: str = "asset-1",
    tenant_id: str = "tenant-a",
    name: str = "My Skill",
    asset_type: str = "skill",
    status: CandidateStatus = CandidateStatus.VALIDATED,
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
    source_uri: str | None = "https://example.com/skill",
    created_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> CandidateAsset:
    now = datetime.now(UTC)
    return CandidateAsset(
        id=asset_id,
        name=name,
        asset_type=asset_type,
        status=status,
        confidence=confidence,
        source_uri=source_uri,
        tenant_id=tenant_id,
        created_at=created_at or now,
        updated_at=now,
        metadata=metadata or {},
    )


def _make_doctor(assets: list[CandidateAsset]) -> SkillsDoctor:
    """Build a SkillsDoctor backed by an in-memory IngestionService pre-populated
    with the given assets."""
    service = IngestionService()
    for asset in assets:
        service._store[asset.id] = asset  # noqa: SLF001
    return SkillsDoctor(service=service)


def _check(report: dict[str, Any], name: str) -> dict[str, str]:
    for c in report["checks"]:
        if c["name"] == name:
            return c
    raise AssertionError(f"Check {name!r} not found in report")


# ---------------------------------------------------------------------------
# Unit: diagnose_asset — healthy asset
# ---------------------------------------------------------------------------


def test_diagnose_asset_healthy_validated_high_confidence() -> None:
    asset = _make_asset(
        status=CandidateStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        source_uri="https://example.com/skill",
    )
    doctor = _make_doctor([asset])
    report = doctor.diagnose_asset(asset.id, asset.tenant_id)

    assert report["status"] == "healthy"
    assert report["asset_id"] == asset.id
    assert report["tenant_id"] == asset.tenant_id

    assert _check(report, "asset_exists")["result"] == "pass"
    assert _check(report, "schema_valid")["result"] == "pass"
    assert _check(report, "source_uri_valid")["result"] == "pass"
    assert _check(report, "confidence_level")["result"] == "pass"
    assert _check(report, "stale_candidate")["result"] == "pass"
    assert _check(report, "review_flag")["result"] == "pass"
    assert _check(report, "quarantine_flag")["result"] == "pass"


# ---------------------------------------------------------------------------
# Unit: diagnose_asset — LOW confidence + quarantine + review_required
# ---------------------------------------------------------------------------


def test_diagnose_asset_critical_low_confidence_quarantine_review() -> None:
    asset = _make_asset(
        status=CandidateStatus.CANDIDATE,
        confidence=ConfidenceLevel.LOW,
        metadata={"review_required": True, "quarantine": True},
    )
    doctor = _make_doctor([asset])
    report = doctor.diagnose_asset(asset.id, asset.tenant_id)

    assert report["status"] == "critical"
    assert _check(report, "confidence_level")["result"] == "warn"
    assert _check(report, "review_flag")["result"] == "warn"
    assert _check(report, "quarantine_flag")["result"] == "critical"


# ---------------------------------------------------------------------------
# Unit: diagnose_asset — stale CANDIDATE (> 7 days)
# ---------------------------------------------------------------------------


def test_diagnose_asset_stale_candidate() -> None:
    stale_time = datetime.now(UTC) - timedelta(days=8)
    asset = _make_asset(
        status=CandidateStatus.CANDIDATE,
        confidence=ConfidenceLevel.MEDIUM,
        created_at=stale_time,
    )
    doctor = _make_doctor([asset])
    report = doctor.diagnose_asset(asset.id, asset.tenant_id)

    assert report["status"] == "warning"
    stale_check = _check(report, "stale_candidate")
    assert stale_check["result"] == "warn"
    assert "8" in stale_check["detail"]


# ---------------------------------------------------------------------------
# Unit: diagnose_asset — invalid source_uri
# ---------------------------------------------------------------------------


def test_diagnose_asset_invalid_source_uri() -> None:
    asset = _make_asset(
        status=CandidateStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        source_uri="ftp://unsupported-scheme.example.com",
    )
    doctor = _make_doctor([asset])
    report = doctor.diagnose_asset(asset.id, asset.tenant_id)

    assert report["status"] == "warning"
    uri_check = _check(report, "source_uri_valid")
    assert uri_check["result"] == "warn"
    assert "ftp://unsupported-scheme.example.com" in uri_check["detail"]


# ---------------------------------------------------------------------------
# Unit: diagnose_asset — non-existent asset_id
# ---------------------------------------------------------------------------


def test_diagnose_asset_nonexistent_returns_critical() -> None:
    doctor = _make_doctor([])
    report = doctor.diagnose_asset("does-not-exist", "tenant-x")

    assert report["status"] == "critical"
    assert len(report["checks"]) == 1
    exists_check = report["checks"][0]
    assert exists_check["name"] == "asset_exists"
    assert exists_check["result"] == "fail"


# ---------------------------------------------------------------------------
# Unit: diagnose_tenant — mixed health assets
# ---------------------------------------------------------------------------


def test_diagnose_tenant_counts_are_correct() -> None:
    healthy_asset = _make_asset(
        asset_id="h1",
        status=CandidateStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        source_uri="https://example.com/h1",
    )
    warning_asset = _make_asset(
        asset_id="w1",
        status=CandidateStatus.CANDIDATE,
        confidence=ConfidenceLevel.LOW,  # warn
        source_uri="https://example.com/w1",
    )
    critical_asset = _make_asset(
        asset_id="c1",
        status=CandidateStatus.CANDIDATE,
        confidence=ConfidenceLevel.HIGH,
        source_uri="https://example.com/c1",
        metadata={"quarantine": True},  # critical
    )

    doctor = _make_doctor([healthy_asset, warning_asset, critical_asset])
    result = doctor.diagnose_tenant("tenant-a")

    assert result["tenant_id"] == "tenant-a"
    assert result["total"] == 3
    assert result["healthy"] == 1
    assert result["warning"] == 1
    assert result["critical"] == 1

    returned_ids = {r["asset_id"] for r in result["assets"]}
    assert returned_ids == {"h1", "w1", "c1"}


# ---------------------------------------------------------------------------
# Unit: summary_report — healthy assets excluded from list
# ---------------------------------------------------------------------------


def test_summary_report_excludes_healthy_assets() -> None:
    healthy_asset = _make_asset(
        asset_id="h2",
        status=CandidateStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        source_uri="https://example.com/h2",
    )
    warning_asset = _make_asset(
        asset_id="w2",
        status=CandidateStatus.CANDIDATE,
        confidence=ConfidenceLevel.LOW,
        source_uri="https://example.com/w2",
    )

    doctor = _make_doctor([healthy_asset, warning_asset])
    result = doctor.summary_report("tenant-a")

    assert result["total"] == 2
    assert result["healthy"] == 1
    assert result["warning"] == 1
    assert result["critical"] == 0

    listed_ids = [r["asset_id"] for r in result["assets"]]
    assert "h2" not in listed_ids
    assert "w2" in listed_ids


# ---------------------------------------------------------------------------
# API fixtures — mirrors test_ingestion_api.py pattern
# ---------------------------------------------------------------------------

_API_TENANT = "tenant-doctor-api"


def _reader_client() -> TestClient:
    token = create_access_token("doctor-user", scopes=["ingestion:read"], tenant_id=_API_TENANT)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture(autouse=True)
def _reset_doctor_service() -> Any:  # type: ignore[misc]
    """Replace the module-level ingestion service and skills doctor with a fresh
    in-memory instance populated with two test assets for each test, then
    restore everything after the test."""
    healthy_asset = _make_asset(
        asset_id="api-h1",
        tenant_id=_API_TENANT,
        status=CandidateStatus.VALIDATED,
        confidence=ConfidenceLevel.HIGH,
        source_uri="https://example.com/api-h1",
    )
    warn_asset = _make_asset(
        asset_id="api-w1",
        tenant_id=_API_TENANT,
        status=CandidateStatus.CANDIDATE,
        confidence=ConfidenceLevel.LOW,
        source_uri="https://example.com/api-w1",
    )

    fresh_service = IngestionService()
    fresh_service._store["api-h1"] = healthy_asset  # noqa: SLF001
    fresh_service._store["api-w1"] = warn_asset  # noqa: SLF001
    fresh_doctor = SkillsDoctor(service=fresh_service)

    saved_service = ingestion_mod._service  # noqa: SLF001
    saved_doctor = ingestion_mod._skills_doctor  # noqa: SLF001
    had_svc = hasattr(app.state, "ingestion_service")
    had_doc = hasattr(app.state, "skills_doctor")
    saved_svc_state = getattr(app.state, "ingestion_service", None)
    saved_doc_state = getattr(app.state, "skills_doctor", None)

    ingestion_mod._service = fresh_service  # noqa: SLF001
    ingestion_mod._skills_doctor = fresh_doctor  # noqa: SLF001
    if had_svc:
        delattr(app.state, "ingestion_service")
    if had_doc:
        delattr(app.state, "skills_doctor")

    yield

    ingestion_mod._service = saved_service  # noqa: SLF001
    ingestion_mod._skills_doctor = saved_doctor  # noqa: SLF001
    if had_svc:
        app.state.ingestion_service = saved_svc_state
    elif hasattr(app.state, "ingestion_service"):
        delattr(app.state, "ingestion_service")
    if had_doc:
        app.state.skills_doctor = saved_doc_state
    elif hasattr(app.state, "skills_doctor"):
        delattr(app.state, "skills_doctor")


# ---------------------------------------------------------------------------
# API: GET /v1/ingestion/doctor/{asset_id}
# ---------------------------------------------------------------------------


def test_api_doctor_asset_report() -> None:
    client = _reader_client()
    resp = client.get("/v1/ingestion/doctor/api-h1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["asset_id"] == "api-h1"
    assert body["status"] == "healthy"
    assert isinstance(body["checks"], list)
    assert len(body["checks"]) == 7
    check_names = [c["name"] for c in body["checks"]]
    assert "asset_exists" in check_names
    assert "quarantine_flag" in check_names


# ---------------------------------------------------------------------------
# API: GET /v1/ingestion/doctor
# ---------------------------------------------------------------------------


def test_api_doctor_tenant_report() -> None:
    client = _reader_client()
    resp = client.get("/v1/ingestion/doctor")
    assert resp.status_code == 200
    body = resp.json()
    assert "tenant_id" in body
    assert body["total"] == 2
    assert body["healthy"] == 1
    assert body["warning"] == 1
    assert body["critical"] == 0
    assert isinstance(body["assets"], list)
    assert len(body["assets"]) == 2


# ---------------------------------------------------------------------------
# API: GET /v1/ingestion/doctor/report — must NOT be caught by {asset_id}
# ---------------------------------------------------------------------------


def test_api_doctor_report_is_not_caught_by_asset_id_route() -> None:
    client = _reader_client()
    resp = client.get("/v1/ingestion/doctor/report")
    assert resp.status_code == 200
    body = resp.json()
    # Summary report shape
    assert "total" in body
    assert body["total"] == 2
    assert body["healthy"] == 1
    assert body["warning"] == 1
    assert body["critical"] == 0
    assert isinstance(body["assets"], list)
    # Healthy asset must NOT appear in the summary assets list.
    listed_ids = [r["asset_id"] for r in body["assets"]]
    assert "api-h1" not in listed_ids
    assert "api-w1" in listed_ids
