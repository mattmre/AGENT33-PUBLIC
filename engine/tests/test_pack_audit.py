"""Tests for pack audit service: health monitoring, audit log, and compliance.

Covers:
- Pack health check: healthy pack, degraded (missing skills), unhealthy (error state)
- Health summary: mixed health states and aggregate metrics
- Audit event recording and retrieval
- Audit log filtering by pack_name and event_type
- Ring buffer eviction at max capacity
- Compliance check: fully compliant, non-compliant (no provenance, no license)
- API routes: health summary, health details, single health, audit log, compliance
"""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent33.api.routes.packs import router  # noqa: I001
from agent33.packs.audit import (
    _MAX_EVENTS,
    PackAuditService,
    PackHealthStatus,
)
from agent33.packs.curation import CurationRecord, CurationStatus, QualityAssessment
from agent33.packs.models import PackSkillEntry, PackStatus
from agent33.packs.provenance_models import PackProvenance, TrustLevel
from agent33.packs.registry import PackRegistry
from agent33.skills.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pack(
    base: Path,
    *,
    name: str = "test-pack",
    license_text: str = "MIT",
    num_skills: int = 1,
) -> Path:
    """Create a minimal valid pack directory."""
    pack_dir = base / name
    pack_dir.mkdir(parents=True, exist_ok=True)

    skills_lines = ""
    for i in range(1, num_skills + 1):
        skills_lines += f"  - name: skill-{i}\n    path: skills/skill-{i}\n"

    (pack_dir / "PACK.yaml").write_text(
        textwrap.dedent(f"""\
        name: {name}
        version: 1.0.0
        description: Pack {name}
        author: tester
        license: {license_text}
        tags:
          - test
          - audit
        category: testing
        skills:
        """)
        + skills_lines,
        encoding="utf-8",
    )

    for i in range(1, num_skills + 1):
        sdir = pack_dir / "skills" / f"skill-{i}"
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "SKILL.md").write_text(
            f"---\nname: skill-{i}\ndescription: Skill {i} from {name}\n---\n# S{i}\n",
            encoding="utf-8",
        )
    return pack_dir


def _make_registry(tmp_path: Path, packs: list[str] | None = None) -> PackRegistry:
    """Create a PackRegistry and load the given packs."""
    sr = SkillRegistry()
    reg = PackRegistry(tmp_path / "packs", sr)
    for pack_name in packs or []:
        _write_pack(tmp_path / "packs", name=pack_name)
    if packs:
        reg.discover(tmp_path / "packs")
    return reg


def _make_provenance() -> PackProvenance:
    """Create a sample provenance."""
    return PackProvenance(
        signer_id="test-signer",
        signature="abc123",
        trust_level=TrustLevel.VERIFIED,
    )


def _create_test_app(
    pack_registry: PackRegistry | None = None,
    pack_audit: PackAuditService | None = None,
) -> FastAPI:
    """Create a minimal FastAPI app with the packs router for testing."""
    app = FastAPI()
    app.include_router(router)

    if pack_registry is not None:
        app.state.pack_registry = pack_registry
    if pack_audit is not None:
        app.state.pack_audit = pack_audit

    from starlette.middleware.base import BaseHTTPMiddleware

    class FakeAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            user = MagicMock()
            user.tenant_id = "test-tenant"
            user.scopes = ["agents:read", "agents:write", "admin"]
            request.state.user = user
            return await call_next(request)

    app.add_middleware(FakeAuthMiddleware)
    return app


# ---------------------------------------------------------------------------
# PackAuditService unit tests
# ---------------------------------------------------------------------------


class TestPackHealthCheckHealthy:
    """Test health check for a pack with no issues."""

    def test_healthy_pack(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path, ["alpha"])
        pack = registry.get("alpha")
        assert pack is not None
        # Attach provenance to avoid "No provenance" issue
        registry._installed["alpha"] = pack.model_copy(update={"provenance": _make_provenance()})

        svc = PackAuditService(registry)
        check = svc.check_pack_health("alpha")

        assert check.pack_name == "alpha"
        assert check.version == "1.0.0"
        assert check.health == PackHealthStatus.HEALTHY
        assert check.issues == []
        assert check.skill_count == 1
        assert check.loaded_skills == 1
        assert check.missing_skills == []
        assert check.has_provenance is True
        assert check.trust_level == "verified"

    def test_healthy_pack_no_provenance_still_healthy(self, tmp_path: Path) -> None:
        """A pack without provenance gets an issue note but is still HEALTHY."""
        registry = _make_registry(tmp_path, ["alpha"])
        svc = PackAuditService(registry)
        check = svc.check_pack_health("alpha")

        assert check.health == PackHealthStatus.HEALTHY
        assert "No provenance signature" in check.issues
        assert check.has_provenance is False

    def test_not_installed_raises(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)
        try:
            svc.check_pack_health("nonexistent")
            assert False, "Expected ValueError"  # noqa: B011
        except ValueError as exc:
            assert "not installed" in str(exc)


class TestPackHealthCheckDegraded:
    """Test health check for packs with degraded status."""

    def test_missing_skills_degraded(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path, ["beta"])
        pack = registry.get("beta")
        assert pack is not None

        # Simulate missing skills by adding extra declared skill not loaded
        extra_skill = PackSkillEntry(name="extra-skill", path="skills/extra-skill")
        modified = pack.model_copy(
            update={
                "skills": list(pack.skills) + [extra_skill],
                "provenance": _make_provenance(),
            }
        )
        registry._installed["beta"] = modified

        svc = PackAuditService(registry)
        check = svc.check_pack_health("beta")

        assert check.health == PackHealthStatus.DEGRADED
        assert "extra-skill" in check.missing_skills
        assert any("Missing skills" in i for i in check.issues)

    def test_disabled_pack_degraded(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path, ["gamma"])
        pack = registry.get("gamma")
        assert pack is not None
        registry._installed["gamma"] = pack.model_copy(
            update={
                "status": PackStatus.DISABLED,
                "provenance": _make_provenance(),
            }
        )

        svc = PackAuditService(registry)
        check = svc.check_pack_health("gamma")

        assert check.health == PackHealthStatus.DEGRADED
        assert any("disabled" in i.lower() for i in check.issues)


class TestPackHealthCheckUnhealthy:
    """Test health check for packs in ERROR state."""

    def test_error_status_unhealthy(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path, ["delta"])
        pack = registry.get("delta")
        assert pack is not None
        registry._installed["delta"] = pack.model_copy(update={"status": PackStatus.ERROR})

        svc = PackAuditService(registry)
        check = svc.check_pack_health("delta")

        assert check.health == PackHealthStatus.UNHEALTHY
        assert any("ERROR" in i for i in check.issues)


class TestPackHealthSummary:
    """Test aggregate health summary with mixed states."""

    def test_mixed_health_states(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path, ["pack-a", "pack-b", "pack-c"])

        # pack-a: healthy (with provenance)
        pa = registry.get("pack-a")
        assert pa is not None
        registry._installed["pack-a"] = pa.model_copy(update={"provenance": _make_provenance()})

        # pack-b: degraded (missing skill)
        pb = registry.get("pack-b")
        assert pb is not None
        extra = PackSkillEntry(name="ghost", path="skills/ghost")
        registry._installed["pack-b"] = pb.model_copy(
            update={
                "skills": list(pb.skills) + [extra],
                "provenance": _make_provenance(),
            }
        )

        # pack-c: unhealthy (error state)
        pc = registry.get("pack-c")
        assert pc is not None
        registry._installed["pack-c"] = pc.model_copy(update={"status": PackStatus.ERROR})

        svc = PackAuditService(registry)
        summary = svc.check_all_health()

        assert summary.total_packs == 3
        assert summary.healthy == 1
        assert summary.degraded == 1
        assert summary.unhealthy == 1
        assert summary.unknown == 0
        assert 0.0 < summary.health_rate < 100.0
        # Top issues should include common ones
        assert len(summary.top_issues) > 0

    def test_empty_registry(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)
        summary = svc.check_all_health()

        assert summary.total_packs == 0
        assert summary.healthy == 0
        assert summary.health_rate == 0.0

    def test_all_healthy(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path, ["one", "two"])
        for name in ["one", "two"]:
            pack = registry.get(name)
            assert pack is not None
            registry._installed[name] = pack.model_copy(update={"provenance": _make_provenance()})

        svc = PackAuditService(registry)
        summary = svc.check_all_health()

        assert summary.total_packs == 2
        assert summary.healthy == 2
        assert summary.health_rate == 100.0


class TestPackHealthWithCuration:
    """Test health check integration with CurationService quality scores."""

    def test_low_quality_score_reported(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path, ["low-q"])

        # Mock curation service returning a low quality score
        mock_curation = MagicMock()
        low_quality = QualityAssessment(
            overall_score=0.3,
            label="low",
            checks=[],
            passed=False,
        )
        mock_record = CurationRecord(
            pack_name="low-q",
            version="1.0.0",
            status=CurationStatus.LISTED,
            quality=low_quality,
        )
        mock_curation.get_curation.return_value = mock_record

        svc = PackAuditService(registry, curation_service=mock_curation)
        check = svc.check_pack_health("low-q")

        assert check.quality_score == 0.3
        assert check.curation_status == "listed"
        assert any("Low quality" in i for i in check.issues)


# ---------------------------------------------------------------------------
# Audit event recording and retrieval
# ---------------------------------------------------------------------------


class TestAuditEventRecording:
    """Test recording and retrieving audit events."""

    def test_record_and_retrieve(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path, ["pack-x"])
        svc = PackAuditService(registry)

        event = svc.record_event(
            pack_name="pack-x",
            event_type="install",
            actor="admin@test.com",
            details={"source": "local"},
            new_version="1.0.0",
        )

        assert event.pack_name == "pack-x"
        assert event.event_type == "install"
        assert event.actor == "admin@test.com"
        assert event.details == {"source": "local"}
        assert event.new_version == "1.0.0"
        assert event.previous_version is None
        assert event.event_id  # UUID is generated

        log = svc.get_audit_log()
        assert len(log) == 1
        assert log[0].event_id == event.event_id

    def test_multiple_events_newest_first(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)

        svc.record_event("pack-a", "install", actor="user1")
        svc.record_event("pack-b", "install", actor="user2")
        svc.record_event("pack-a", "upgrade", actor="user1")

        log = svc.get_audit_log()
        assert len(log) == 3
        # Newest first
        assert log[0].event_type == "upgrade"
        assert log[1].pack_name == "pack-b"
        assert log[2].event_type == "install"
        assert log[2].pack_name == "pack-a"

    def test_filter_by_pack_name(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)

        svc.record_event("pack-a", "install", actor="user1")
        svc.record_event("pack-b", "install", actor="user2")
        svc.record_event("pack-a", "upgrade", actor="user1")

        log = svc.get_audit_log(pack_name="pack-a")
        assert len(log) == 2
        assert all(e.pack_name == "pack-a" for e in log)

    def test_filter_by_event_type(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)

        svc.record_event("pack-a", "install", actor="user1")
        svc.record_event("pack-b", "upgrade", actor="user2")
        svc.record_event("pack-c", "install", actor="user3")

        log = svc.get_audit_log(event_type="install")
        assert len(log) == 2
        assert all(e.event_type == "install" for e in log)

    def test_filter_combined(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)

        svc.record_event("pack-a", "install", actor="user1")
        svc.record_event("pack-a", "upgrade", actor="user1")
        svc.record_event("pack-b", "install", actor="user2")

        log = svc.get_audit_log(pack_name="pack-a", event_type="upgrade")
        assert len(log) == 1
        assert log[0].event_type == "upgrade"
        assert log[0].pack_name == "pack-a"

    def test_limit(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)

        for i in range(10):
            svc.record_event(f"pack-{i}", "install", actor="user")

        log = svc.get_audit_log(limit=3)
        assert len(log) == 3

    def test_ring_buffer_eviction(self, tmp_path: Path) -> None:
        """Events beyond _MAX_EVENTS are evicted (oldest first)."""
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)

        for i in range(_MAX_EVENTS + 50):
            svc.record_event(f"pack-{i}", "install", actor="user")

        # Internal buffer should be capped
        assert len(svc._events) == _MAX_EVENTS

        # The oldest 50 events should be gone
        all_log = svc.get_audit_log(limit=_MAX_EVENTS)
        pack_names = {e.pack_name for e in all_log}
        # pack-0 through pack-49 should have been evicted
        assert "pack-0" not in pack_names
        assert f"pack-{_MAX_EVENTS + 49}" in pack_names

    def test_version_tracking(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)

        svc.record_event(
            "pack-x",
            "upgrade",
            actor="admin",
            previous_version="1.0.0",
            new_version="2.0.0",
        )

        log = svc.get_audit_log()
        assert log[0].previous_version == "1.0.0"
        assert log[0].new_version == "2.0.0"


# ---------------------------------------------------------------------------
# Compliance checks
# ---------------------------------------------------------------------------


class TestComplianceCheck:
    """Test compliance verification for packs."""

    def test_fully_compliant(self, tmp_path: Path) -> None:
        """A pack with provenance, license, quality, and no conflicts is compliant."""
        registry = _make_registry(tmp_path, ["compliant-pack"])
        pack = registry.get("compliant-pack")
        assert pack is not None
        registry._installed["compliant-pack"] = pack.model_copy(
            update={
                "provenance": _make_provenance(),
                "license": "MIT",
            }
        )

        svc = PackAuditService(registry)
        report = svc.compliance_check("compliant-pack")

        assert report.pack_name == "compliant-pack"
        assert report.compliant is True
        assert len(report.checks) == 5
        assert all(c["passed"] for c in report.checks)

    def test_no_provenance_non_compliant(self, tmp_path: Path) -> None:
        """A pack without provenance fails the has_provenance check."""
        registry = _make_registry(tmp_path, ["unsigned"])
        pack = registry.get("unsigned")
        assert pack is not None
        # Ensure it has a license so only provenance fails
        registry._installed["unsigned"] = pack.model_copy(update={"license": "Apache-2.0"})

        svc = PackAuditService(registry)
        report = svc.compliance_check("unsigned")

        assert report.compliant is False
        prov_check = next(c for c in report.checks if c["name"] == "has_provenance")
        assert prov_check["passed"] is False
        assert "No provenance" in prov_check["reason"]

    def test_no_license_non_compliant(self, tmp_path: Path) -> None:
        """A pack without a license fails the has_license check."""
        registry = _make_registry(tmp_path, ["no-license"])
        pack = registry.get("no-license")
        assert pack is not None
        registry._installed["no-license"] = pack.model_copy(
            update={
                "provenance": _make_provenance(),
                "license": "",
            }
        )

        svc = PackAuditService(registry)
        report = svc.compliance_check("no-license")

        assert report.compliant is False
        lic_check = next(c for c in report.checks if c["name"] == "has_license")
        assert lic_check["passed"] is False
        assert "No license" in lic_check["reason"]

    def test_skill_conflict_non_compliant(self, tmp_path: Path) -> None:
        """A pack with skill name conflicts fails the no_skill_conflicts check."""
        # Create two packs with the same skill name
        _write_pack(tmp_path / "packs", name="conflict-a")
        _write_pack(tmp_path / "packs", name="conflict-b")

        sr = SkillRegistry()
        registry = PackRegistry(tmp_path / "packs", sr)
        registry.discover(tmp_path / "packs")

        # Both packs have skill-1, so there should be a conflict
        pa = registry.get("conflict-a")
        pb = registry.get("conflict-b")
        assert pa is not None
        assert pb is not None

        # Ensure both pass other checks
        for name in ["conflict-a", "conflict-b"]:
            pack = registry.get(name)
            assert pack is not None
            registry._installed[name] = pack.model_copy(
                update={
                    "provenance": _make_provenance(),
                    "license": "MIT",
                }
            )

        svc = PackAuditService(registry)
        report = svc.compliance_check("conflict-a")

        assert report.compliant is False
        conflict_check = next(c for c in report.checks if c["name"] == "no_skill_conflicts")
        assert conflict_check["passed"] is False
        assert "conflict-b" in conflict_check["reason"]

    def test_low_quality_non_compliant(self, tmp_path: Path) -> None:
        """Low curation quality score fails the quality_threshold check."""
        registry = _make_registry(tmp_path, ["low-q-compliance"])
        pack = registry.get("low-q-compliance")
        assert pack is not None
        registry._installed["low-q-compliance"] = pack.model_copy(
            update={
                "provenance": _make_provenance(),
                "license": "MIT",
            }
        )

        mock_curation = MagicMock()
        low_quality = QualityAssessment(
            overall_score=0.3,
            label="low",
            checks=[],
            passed=False,
        )
        mock_record = CurationRecord(
            pack_name="low-q-compliance",
            version="1.0.0",
            status=CurationStatus.LISTED,
            quality=low_quality,
        )
        mock_curation.get_curation.return_value = mock_record

        svc = PackAuditService(registry, curation_service=mock_curation)
        report = svc.compliance_check("low-q-compliance")

        assert report.compliant is False
        q_check = next(c for c in report.checks if c["name"] == "quality_threshold")
        assert q_check["passed"] is False
        assert "below 0.5 threshold" in q_check["reason"]

    def test_not_installed_raises(self, tmp_path: Path) -> None:
        registry = _make_registry(tmp_path)
        svc = PackAuditService(registry)
        try:
            svc.compliance_check("ghost-pack")
            assert False, "Expected ValueError"  # noqa: B011
        except ValueError as exc:
            assert "not installed" in str(exc)


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestPackAuditRoutes:
    """Test pack audit API endpoints."""

    def _setup(self, tmp_path: Path) -> tuple[PackRegistry, PackAuditService, TestClient]:
        registry = _make_registry(tmp_path, ["route-pack"])
        pack = registry.get("route-pack")
        assert pack is not None
        registry._installed["route-pack"] = pack.model_copy(
            update={
                "provenance": _make_provenance(),
                "license": "MIT",
            }
        )
        svc = PackAuditService(registry)
        app = _create_test_app(pack_registry=registry, pack_audit=svc)
        client = TestClient(app)
        return registry, svc, client

    def test_get_health_summary(self, tmp_path: Path) -> None:
        _, _, client = self._setup(tmp_path)
        resp = client.get("/v1/packs/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_packs"] == 1
        assert data["healthy"] == 1
        assert data["health_rate"] == 100.0
        assert "generated_at" in data

    def test_get_health_details(self, tmp_path: Path) -> None:
        _, _, client = self._setup(tmp_path)
        resp = client.get("/v1/packs/health/details")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        detail = data["details"][0]
        assert detail["pack_name"] == "route-pack"
        assert detail["health"] == "healthy"
        assert detail["has_provenance"] is True

    def test_get_single_pack_health(self, tmp_path: Path) -> None:
        _, _, client = self._setup(tmp_path)
        resp = client.get("/v1/packs/health/route-pack")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pack_name"] == "route-pack"
        assert data["health"] == "healthy"
        assert data["version"] == "1.0.0"

    def test_get_single_pack_health_not_found(self, tmp_path: Path) -> None:
        _, _, client = self._setup(tmp_path)
        resp = client.get("/v1/packs/health/nonexistent")
        assert resp.status_code == 404

    def test_get_audit_log(self, tmp_path: Path) -> None:
        _, svc, client = self._setup(tmp_path)
        svc.record_event("route-pack", "install", actor="admin")
        svc.record_event("route-pack", "upgrade", actor="admin")

        resp = client.get("/v1/packs/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["events"][0]["event_type"] == "upgrade"

    def test_get_audit_log_filtered(self, tmp_path: Path) -> None:
        _, svc, client = self._setup(tmp_path)
        svc.record_event("route-pack", "install", actor="admin")
        svc.record_event("other-pack", "install", actor="admin")

        resp = client.get("/v1/packs/audit", params={"pack_name": "route-pack"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["events"][0]["pack_name"] == "route-pack"

    def test_get_pack_audit_log_by_name(self, tmp_path: Path) -> None:
        _, svc, client = self._setup(tmp_path)
        svc.record_event("route-pack", "install", actor="admin")
        svc.record_event("other-pack", "install", actor="admin")

        resp = client.get("/v1/packs/audit/route-pack")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["events"][0]["pack_name"] == "route-pack"

    def test_get_compliance(self, tmp_path: Path) -> None:
        _, _, client = self._setup(tmp_path)
        resp = client.get("/v1/packs/compliance/route-pack")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pack_name"] == "route-pack"
        assert data["compliant"] is True
        assert len(data["checks"]) == 5
        # Verify each check has name, passed, reason fields
        for check in data["checks"]:
            assert "name" in check
            assert "passed" in check
            assert "reason" in check

    def test_get_compliance_not_found(self, tmp_path: Path) -> None:
        _, _, client = self._setup(tmp_path)
        resp = client.get("/v1/packs/compliance/ghost")
        assert resp.status_code == 404

    def test_check_all_compliance(self, tmp_path: Path) -> None:
        _, _, client = self._setup(tmp_path)
        resp = client.post("/v1/packs/compliance/check-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["compliant"] == 1
        assert data["non_compliant"] == 0
        report = data["reports"][0]
        assert report["pack_name"] == "route-pack"
        assert report["compliant"] is True

    def test_health_service_not_initialized(self) -> None:
        """Endpoints return 503 when pack_audit is not on app.state."""
        app = _create_test_app()
        client = TestClient(app)

        assert client.get("/v1/packs/health").status_code == 503
        assert client.get("/v1/packs/health/details").status_code == 503
        assert client.get("/v1/packs/health/test").status_code == 503
        assert client.get("/v1/packs/audit").status_code == 503
        assert client.get("/v1/packs/audit/test").status_code == 503
        assert client.get("/v1/packs/compliance/test").status_code == 503
        assert client.post("/v1/packs/compliance/check-all").status_code == 503


class TestPackAuditRoutesMixed:
    """Test API routes with mixed compliance/health states."""

    def test_check_all_compliance_mixed(self, tmp_path: Path) -> None:
        """Batch compliance with one compliant and one non-compliant pack."""
        # Use different skill names to avoid conflict-based non-compliance
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir(parents=True, exist_ok=True)

        # good-pack with skill-g
        good_dir = packs_dir / "good-pack"
        good_dir.mkdir()
        (good_dir / "PACK.yaml").write_text(
            textwrap.dedent("""\
            name: good-pack
            version: 1.0.0
            description: Good pack
            author: tester
            license: MIT
            tags:
              - test
            skills:
              - name: skill-g
                path: skills/skill-g
            """),
            encoding="utf-8",
        )
        sg = good_dir / "skills" / "skill-g"
        sg.mkdir(parents=True)
        (sg / "SKILL.md").write_text(
            "---\nname: skill-g\ndescription: Good skill\n---\n# SG\n",
            encoding="utf-8",
        )

        # bad-pack with skill-b
        bad_dir = packs_dir / "bad-pack"
        bad_dir.mkdir()
        (bad_dir / "PACK.yaml").write_text(
            textwrap.dedent("""\
            name: bad-pack
            version: 1.0.0
            description: Bad pack
            author: tester
            tags:
              - test
            skills:
              - name: skill-b
                path: skills/skill-b
            """),
            encoding="utf-8",
        )
        sb = bad_dir / "skills" / "skill-b"
        sb.mkdir(parents=True)
        (sb / "SKILL.md").write_text(
            "---\nname: skill-b\ndescription: Bad skill\n---\n# SB\n",
            encoding="utf-8",
        )

        sr = SkillRegistry()
        registry = PackRegistry(packs_dir, sr)
        registry.discover(packs_dir)

        good = registry.get("good-pack")
        assert good is not None
        registry._installed["good-pack"] = good.model_copy(
            update={"provenance": _make_provenance(), "license": "MIT"}
        )

        bad = registry.get("bad-pack")
        assert bad is not None
        registry._installed["bad-pack"] = bad.model_copy(
            update={"license": ""}  # no license, no provenance
        )

        svc = PackAuditService(registry)
        app = _create_test_app(pack_registry=registry, pack_audit=svc)
        client = TestClient(app)

        resp = client.post("/v1/packs/compliance/check-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert data["compliant"] == 1
        assert data["non_compliant"] == 1

    def test_health_details_multiple_states(self, tmp_path: Path) -> None:
        """Health details endpoint shows mixed states correctly."""
        registry = _make_registry(tmp_path, ["h-pack", "d-pack"])

        hp = registry.get("h-pack")
        assert hp is not None
        registry._installed["h-pack"] = hp.model_copy(update={"provenance": _make_provenance()})

        dp = registry.get("d-pack")
        assert dp is not None
        extra = PackSkillEntry(name="phantom", path="skills/phantom")
        registry._installed["d-pack"] = dp.model_copy(
            update={
                "skills": list(dp.skills) + [extra],
                "provenance": _make_provenance(),
            }
        )

        svc = PackAuditService(registry)
        app = _create_test_app(pack_registry=registry, pack_audit=svc)
        client = TestClient(app)

        resp = client.get("/v1/packs/health/details")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

        health_map = {d["pack_name"]: d["health"] for d in data["details"]}
        assert health_map["h-pack"] == "healthy"
        assert health_map["d-pack"] == "degraded"
