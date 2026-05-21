"""Tests for trust analytics dashboard (Phase 33 / S23).

Covers:
  - TrustOverview: mixed signed/unsigned packs, all unsigned, all signed
  - TrustChainEntry: policy evaluation, trust level mapping
  - Batch signature verification with and without verification key
  - Audit trail retrieval from ProvenanceCollector
  - CurationService stats integration
  - API routes: dashboard, overview, chain, audit, verify-all
  - Edge cases: empty registry, no provenance collector, no curation service
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

if TYPE_CHECKING:
    from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent33.api.routes.packs import router
from agent33.packs.curation import CurationRecord, CurationStatus
from agent33.packs.provenance import sign_pack
from agent33.packs.provenance_models import (
    PackProvenance,
    PackTrustPolicy,
    TrustLevel,
)
from agent33.packs.registry import PackRegistry
from agent33.packs.trust_analytics import (
    TrustAnalyticsService,
    TrustAuditRecord,
    TrustChainEntry,
    TrustDashboardSummary,
    TrustOverview,
)
from agent33.packs.trust_manager import TrustPolicyManager
from agent33.provenance.collector import ProvenanceCollector
from agent33.provenance.models import ProvenanceReceipt, ProvenanceSource
from agent33.services.orchestration_state import OrchestrationStateStore
from agent33.skills.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pack(
    base: Path,
    *,
    name: str = "test-pack",
    version: str = "1.0.0",
) -> Path:
    """Create a minimal valid pack directory."""
    pack_dir = base / name
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "PACK.yaml").write_text(
        textwrap.dedent(f"""\
        name: {name}
        version: {version}
        description: Pack {name}
        author: tester
        tags:
          - test
        skills:
          - name: skill-1
            path: skills/skill-1
        """),
        encoding="utf-8",
    )
    sdir = pack_dir / "skills" / "skill-1"
    sdir.mkdir(parents=True)
    (sdir / "SKILL.md").write_text(
        f"---\nname: skill-1\ndescription: Skill from {name}\n---\n# S1\n",
        encoding="utf-8",
    )
    return pack_dir


def _make_registry(
    tmp_path: Path,
    *,
    pack_names: list[str] | None = None,
    sign_names: list[str] | None = None,
    signing_key: str = "test-key",
    trust_policy: PackTrustPolicy | None = None,
) -> tuple[PackRegistry, TrustPolicyManager, Path]:
    """Create a registry with optional pre-installed and signed packs."""
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir()
    state_store = OrchestrationStateStore(str(tmp_path / "state.json"))
    trust_manager = TrustPolicyManager(state_store)
    if trust_policy is not None:
        trust_manager.update_policy(
            require_signature=trust_policy.require_signature,
            min_trust_level=trust_policy.min_trust_level,
            allowed_signers=trust_policy.allowed_signers or None,
        )
    skill_reg = SkillRegistry()
    registry = PackRegistry(
        packs_dir=packs_dir,
        skill_registry=skill_reg,
        trust_policy_manager=trust_manager,
    )

    names = pack_names or []
    sign_set = set(sign_names or [])

    for name in names:
        pack_dir = _write_pack(packs_dir, name=name)
        pack = registry.load_pack(pack_dir)
        provenance: PackProvenance | None = None
        if name in sign_set:
            from agent33.packs.loader import load_pack_manifest

            manifest = load_pack_manifest(pack_dir)
            provenance = sign_pack(
                manifest, signing_key, signer_id="ci-bot", trust_level=TrustLevel.VERIFIED
            )
        registry._installed[pack.name] = pack.model_copy(update={"provenance": provenance})

    return registry, trust_manager, packs_dir


def _create_test_app(
    pack_registry: PackRegistry | None = None,
    trust_analytics: TrustAnalyticsService | None = None,
    trust_manager: TrustPolicyManager | None = None,
) -> FastAPI:
    """Create a minimal FastAPI app with the packs router for testing."""
    app = FastAPI()
    app.include_router(router)

    if pack_registry is not None:
        app.state.pack_registry = pack_registry
    if trust_analytics is not None:
        app.state.trust_analytics = trust_analytics
    if trust_manager is not None:
        app.state.pack_trust_manager = trust_manager

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


class _FakeCurationService:
    """Minimal curation service stand-in for trust analytics tests."""

    def __init__(
        self,
        records: list[CurationRecord] | None = None,
    ) -> None:
        self._records = records or []

    def list_curated(
        self,
        *,
        status: CurationStatus | None = None,
        featured_only: bool = False,
    ) -> list[CurationRecord]:
        results: list[CurationRecord] = []
        for r in self._records:
            if status is not None and r.status != status:
                continue
            if featured_only and not r.featured:
                continue
            results.append(r)
        return results


# ===========================================================================
# TrustOverview tests
# ===========================================================================


class TestTrustOverview:
    """Test get_overview with different pack mixes."""

    def test_overview_mixed_signed_unsigned(self, tmp_path: Path) -> None:
        """Mixed signed/unsigned packs produce correct counts and signature rate."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["alpha", "bravo", "charlie"],
            sign_names=["alpha", "charlie"],
        )
        svc = TrustAnalyticsService(registry, trust_manager)
        overview = svc.get_overview()

        assert overview.total_packs == 3
        assert overview.signed_packs == 2
        assert overview.unsigned_packs == 1
        assert overview.signature_rate == round(2 / 3 * 100, 2)
        assert overview.by_trust_level.get("verified", 0) == 2
        assert overview.by_trust_level.get("untrusted", 0) == 1
        # Default policy: no signature required, all pass
        assert overview.policy_compliant == 3
        assert overview.policy_violations == 0

    def test_overview_all_unsigned(self, tmp_path: Path) -> None:
        """All unsigned packs show 0% signature rate."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["delta", "echo"],
            sign_names=[],
        )
        svc = TrustAnalyticsService(registry, trust_manager)
        overview = svc.get_overview()

        assert overview.total_packs == 2
        assert overview.signed_packs == 0
        assert overview.unsigned_packs == 2
        assert overview.signature_rate == 0.0
        assert overview.by_trust_level.get("untrusted", 0) == 2

    def test_overview_empty_registry(self, tmp_path: Path) -> None:
        """Empty registry: all counts zero, no division error."""
        registry, trust_manager, _ = _make_registry(tmp_path, pack_names=[])
        svc = TrustAnalyticsService(registry, trust_manager)
        overview = svc.get_overview()

        assert overview.total_packs == 0
        assert overview.signed_packs == 0
        assert overview.unsigned_packs == 0
        assert overview.signature_rate == 0.0
        assert overview.policy_compliant == 0
        assert overview.policy_violations == 0

    def test_overview_policy_violations_with_strict_policy(self, tmp_path: Path) -> None:
        """Strict policy flags unsigned packs as violations."""
        policy = PackTrustPolicy(require_signature=True)
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["fox", "golf"],
            sign_names=["fox"],
            trust_policy=policy,
        )
        svc = TrustAnalyticsService(registry, trust_manager)
        overview = svc.get_overview()

        assert overview.total_packs == 2
        assert overview.policy_compliant == 1
        assert overview.policy_violations == 1

    def test_overview_all_signed(self, tmp_path: Path) -> None:
        """All signed: 100% rate, zero violations with default policy."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["hotel", "india"],
            sign_names=["hotel", "india"],
        )
        svc = TrustAnalyticsService(registry, trust_manager)
        overview = svc.get_overview()

        assert overview.total_packs == 2
        assert overview.signed_packs == 2
        assert overview.unsigned_packs == 0
        assert overview.signature_rate == 100.0


# ===========================================================================
# TrustChainEntry tests
# ===========================================================================


class TestTrustChain:
    """Test get_trust_chain with policy evaluation."""

    def test_chain_entries_match_installed_packs(self, tmp_path: Path) -> None:
        """Each installed pack gets exactly one chain entry."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["pack-a", "pack-b"],
            sign_names=["pack-a"],
        )
        svc = TrustAnalyticsService(registry, trust_manager)
        chain = svc.get_trust_chain()

        assert len(chain) == 2
        names = {e.pack_name for e in chain}
        assert names == {"pack-a", "pack-b"}

    def test_chain_signed_pack_has_signer_info(self, tmp_path: Path) -> None:
        """Signed pack chain entry includes signer_id and trust_level."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["signed-pack"],
            sign_names=["signed-pack"],
        )
        svc = TrustAnalyticsService(registry, trust_manager)
        chain = svc.get_trust_chain()

        assert len(chain) == 1
        entry = chain[0]
        assert entry.pack_name == "signed-pack"
        assert entry.trust_level == "verified"
        assert entry.signer_id == "ci-bot"
        assert entry.signed_at is not None
        assert entry.policy_decision == "ALLOW"

    def test_chain_unsigned_pack_is_untrusted(self, tmp_path: Path) -> None:
        """Unsigned pack chain entry shows untrusted level and no signer."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["unsigned-pack"],
            sign_names=[],
        )
        svc = TrustAnalyticsService(registry, trust_manager)
        chain = svc.get_trust_chain()

        entry = chain[0]
        assert entry.trust_level == "untrusted"
        assert entry.signer_id is None
        assert entry.signed_at is None
        assert entry.signature_valid is None

    def test_chain_policy_deny_for_unsigned_strict(self, tmp_path: Path) -> None:
        """Unsigned pack shows DENY policy_decision under strict policy."""
        policy = PackTrustPolicy(require_signature=True)
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["no-sig"],
            sign_names=[],
            trust_policy=policy,
        )
        svc = TrustAnalyticsService(registry, trust_manager)
        chain = svc.get_trust_chain()

        entry = chain[0]
        assert entry.policy_decision == "DENY"

    def test_chain_signature_valid_with_key(self, tmp_path: Path) -> None:
        """When verification_key is set, chain entry includes signature_valid."""
        registry, trust_manager, packs_dir = _make_registry(
            tmp_path,
            pack_names=["verifiable"],
            sign_names=["verifiable"],
            signing_key="my-key",
        )
        svc = TrustAnalyticsService(registry, trust_manager, verification_key="my-key")
        chain = svc.get_trust_chain()

        entry = chain[0]
        assert entry.signature_valid is True

    def test_chain_signature_invalid_with_wrong_key(self, tmp_path: Path) -> None:
        """Wrong verification key produces signature_valid=False."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["bad-key"],
            sign_names=["bad-key"],
            signing_key="correct-key",
        )
        svc = TrustAnalyticsService(registry, trust_manager, verification_key="wrong-key")
        chain = svc.get_trust_chain()

        entry = chain[0]
        assert entry.signature_valid is False


# ===========================================================================
# Batch signature verification tests
# ===========================================================================


class TestBatchVerification:
    """Test verify_all_signatures."""

    def test_verify_all_valid(self, tmp_path: Path) -> None:
        """All signed packs verify successfully with correct key."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["v1", "v2"],
            sign_names=["v1", "v2"],
            signing_key="shared-key",
        )
        svc = TrustAnalyticsService(registry, trust_manager, verification_key="shared-key")
        results = svc.verify_all_signatures()

        assert len(results) == 2
        for r in results:
            assert r["valid"] is True
            assert r["error"] == ""
            assert r["signer_id"] == "ci-bot"

    def test_verify_all_skips_unsigned(self, tmp_path: Path) -> None:
        """Unsigned packs are excluded from batch verification."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["signed", "unsigned"],
            sign_names=["signed"],
            signing_key="k",
        )
        svc = TrustAnalyticsService(registry, trust_manager, verification_key="k")
        results = svc.verify_all_signatures()

        assert len(results) == 1
        assert results[0]["pack_name"] == "signed"

    def test_verify_all_no_key_reports_error(self, tmp_path: Path) -> None:
        """Without a verification key, each result reports an error."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["s1"],
            sign_names=["s1"],
        )
        svc = TrustAnalyticsService(registry, trust_manager, verification_key="")
        results = svc.verify_all_signatures()

        assert len(results) == 1
        assert results[0]["valid"] is None
        assert "no verification key" in results[0]["error"]

    def test_verify_all_wrong_key_fails(self, tmp_path: Path) -> None:
        """Wrong verification key produces valid=False."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["mismatch"],
            sign_names=["mismatch"],
            signing_key="right",
        )
        svc = TrustAnalyticsService(registry, trust_manager, verification_key="wrong")
        results = svc.verify_all_signatures()

        assert len(results) == 1
        assert results[0]["valid"] is False

    def test_verify_all_empty_registry(self, tmp_path: Path) -> None:
        """Empty registry returns empty results."""
        registry, trust_manager, _ = _make_registry(tmp_path, pack_names=[])
        svc = TrustAnalyticsService(registry, trust_manager)
        results = svc.verify_all_signatures()
        assert results == []


# ===========================================================================
# Audit trail tests
# ===========================================================================


class TestAuditTrail:
    """Test get_audit_trail from ProvenanceCollector."""

    def test_audit_trail_from_collector(self) -> None:
        """Audit trail converts PACK_INSTALL receipts into TrustAuditRecords."""
        collector = ProvenanceCollector(max_receipts=100)
        collector.record(
            ProvenanceReceipt(
                source=ProvenanceSource.PACK_INSTALL,
                actor="admin",
                metadata={"pack_name": "my-pack", "event_type": "install", "version": "1.0.0"},
            )
        )
        collector.record(
            ProvenanceReceipt(
                source=ProvenanceSource.PACK_INSTALL,
                actor="admin",
                metadata={"pack_name": "other-pack", "event_type": "upgrade"},
            )
        )
        # A non-pack receipt should be excluded
        collector.record(
            ProvenanceReceipt(
                source=ProvenanceSource.SESSION_SPAWN,
                actor="system",
                metadata={"session_id": "s1"},
            )
        )

        trust_manager = MagicMock()
        trust_manager.get_policy.return_value = PackTrustPolicy()
        pack_registry = MagicMock()
        pack_registry.list_installed.return_value = []

        svc = TrustAnalyticsService(pack_registry, trust_manager, provenance_collector=collector)
        records = svc.get_audit_trail(limit=10)

        # Should get 2 PACK_INSTALL records, not the SESSION_SPAWN one
        assert len(records) == 2
        pack_names = {r.pack_name for r in records}
        assert pack_names == {"my-pack", "other-pack"}

    def test_audit_trail_respects_limit(self) -> None:
        """Audit trail limit parameter is passed through."""
        collector = ProvenanceCollector(max_receipts=100)
        for i in range(10):
            collector.record(
                ProvenanceReceipt(
                    source=ProvenanceSource.PACK_INSTALL,
                    metadata={"pack_name": f"pack-{i}", "event_type": "install"},
                )
            )

        trust_manager = MagicMock()
        trust_manager.get_policy.return_value = PackTrustPolicy()
        pack_registry = MagicMock()
        pack_registry.list_installed.return_value = []

        svc = TrustAnalyticsService(pack_registry, trust_manager, provenance_collector=collector)
        records = svc.get_audit_trail(limit=3)
        assert len(records) == 3

    def test_audit_trail_no_collector(self, tmp_path: Path) -> None:
        """Without a provenance collector, returns empty list."""
        registry, trust_manager, _ = _make_registry(tmp_path, pack_names=[])
        svc = TrustAnalyticsService(registry, trust_manager, provenance_collector=None)
        records = svc.get_audit_trail()
        assert records == []


# ===========================================================================
# Dashboard composite tests
# ===========================================================================


class TestDashboardSummary:
    """Test get_dashboard composite output."""

    def test_dashboard_includes_all_sections(self, tmp_path: Path) -> None:
        """Dashboard summary includes overview, chain, audit, policy."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["d1", "d2"],
            sign_names=["d1"],
        )
        svc = TrustAnalyticsService(registry, trust_manager)
        dashboard = svc.get_dashboard()

        assert isinstance(dashboard, TrustDashboardSummary)
        assert dashboard.overview.total_packs == 2
        assert len(dashboard.trust_chain) == 2
        assert isinstance(dashboard.current_policy, dict)
        assert "require_signature" in dashboard.current_policy
        assert dashboard.curation_stats is None  # no curation service

    def test_dashboard_with_curation_stats(self, tmp_path: Path) -> None:
        """Dashboard includes curation stats when CurationService is available."""
        registry, trust_manager, _ = _make_registry(tmp_path, pack_names=["c1"], sign_names=[])
        curation_svc = _FakeCurationService(
            records=[
                CurationRecord(
                    pack_name="c1",
                    version="1.0.0",
                    status=CurationStatus.LISTED,
                    featured=True,
                ),
                CurationRecord(
                    pack_name="c2",
                    version="1.0.0",
                    status=CurationStatus.SUBMITTED,
                    featured=False,
                ),
            ]
        )
        svc = TrustAnalyticsService(registry, trust_manager, curation_service=curation_svc)
        dashboard = svc.get_dashboard()

        assert dashboard.curation_stats is not None
        assert dashboard.curation_stats["total_records"] == 2
        assert dashboard.curation_stats["featured_count"] == 1
        assert dashboard.curation_stats["by_status"]["listed"] == 1
        assert dashboard.curation_stats["by_status"]["submitted"] == 1

    def test_dashboard_serializes_to_json(self, tmp_path: Path) -> None:
        """Dashboard summary can be serialized to JSON without errors."""
        registry, trust_manager, _ = _make_registry(tmp_path, pack_names=["j1"], sign_names=["j1"])
        svc = TrustAnalyticsService(registry, trust_manager)
        dashboard = svc.get_dashboard()
        json_data = dashboard.model_dump(mode="json")

        assert isinstance(json_data, dict)
        assert "overview" in json_data
        assert "trust_chain" in json_data
        assert "current_policy" in json_data


# ===========================================================================
# API route tests
# ===========================================================================


class TestTrustDashboardRoutes:
    """Test trust dashboard API endpoints."""

    def _setup(
        self,
        tmp_path: Path,
        *,
        pack_names: list[str] | None = None,
        sign_names: list[str] | None = None,
        signing_key: str = "test-key",
    ) -> tuple[TestClient, TrustAnalyticsService]:
        """Create test client with full trust analytics wiring."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=pack_names or ["rt-1", "rt-2"],
            sign_names=sign_names or ["rt-1"],
            signing_key=signing_key,
        )
        svc = TrustAnalyticsService(registry, trust_manager, verification_key=signing_key)
        app = _create_test_app(
            pack_registry=registry,
            trust_analytics=svc,
            trust_manager=trust_manager,
        )
        client = TestClient(app)
        return client, svc

    def test_dashboard_route_returns_full_summary(self, tmp_path: Path) -> None:
        """GET /trust/dashboard returns full composite summary."""
        client, _ = self._setup(tmp_path)
        resp = client.get("/v1/packs/trust/dashboard")
        assert resp.status_code == 200
        data = resp.json()
        assert "overview" in data
        assert "trust_chain" in data
        assert "recent_audit" in data
        assert "current_policy" in data
        assert data["overview"]["total_packs"] == 2

    def test_overview_route(self, tmp_path: Path) -> None:
        """GET /trust/overview returns aggregate metrics."""
        client, _ = self._setup(tmp_path)
        resp = client.get("/v1/packs/trust/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_packs"] == 2
        assert data["signed_packs"] == 1
        assert data["unsigned_packs"] == 1
        assert data["signature_rate"] == 50.0

    def test_chain_route(self, tmp_path: Path) -> None:
        """GET /trust/chain returns entries for each installed pack."""
        client, _ = self._setup(tmp_path)
        resp = client.get("/v1/packs/trust/chain")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["entries"]) == 2
        names = {e["pack_name"] for e in data["entries"]}
        assert names == {"rt-1", "rt-2"}

    def test_audit_route_default_limit(self, tmp_path: Path) -> None:
        """GET /trust/audit returns empty list when no provenance collector."""
        client, _ = self._setup(tmp_path)
        resp = client.get("/v1/packs/trust/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["records"] == []
        assert data["count"] == 0

    def test_audit_route_with_limit_param(self, tmp_path: Path) -> None:
        """GET /trust/audit respects the limit query parameter."""
        client, _ = self._setup(tmp_path)
        resp = client.get("/v1/packs/trust/audit", params={"limit": 10})
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_verify_all_route(self, tmp_path: Path) -> None:
        """POST /trust/verify-all batch-verifies all signed packs."""
        client, _ = self._setup(tmp_path, signing_key="verify-key")
        resp = client.post("/v1/packs/trust/verify-all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_verified"] == 1  # only rt-1 is signed
        assert data["results"][0]["pack_name"] == "rt-1"
        assert data["results"][0]["valid"] is True

    def test_verify_all_route_all_valid_flag(self, tmp_path: Path) -> None:
        """POST /trust/verify-all sets all_valid=True when all pass."""
        client, _ = self._setup(
            tmp_path,
            pack_names=["s1", "s2"],
            sign_names=["s1", "s2"],
            signing_key="k",
        )
        resp = client.post("/v1/packs/trust/verify-all")
        data = resp.json()
        assert data["all_valid"] is True
        assert data["total_verified"] == 2

    def test_routes_return_503_without_service(self) -> None:
        """Routes return 503 when trust analytics not initialized."""
        app = _create_test_app(pack_registry=None, trust_analytics=None)
        client = TestClient(app)

        for path in [
            "/v1/packs/trust/dashboard",
            "/v1/packs/trust/overview",
            "/v1/packs/trust/chain",
            "/v1/packs/trust/audit",
        ]:
            resp = client.get(path)
            assert resp.status_code == 503, f"Expected 503 for {path}, got {resp.status_code}"

        resp = client.post("/v1/packs/trust/verify-all")
        assert resp.status_code == 503


class TestTrustDashboardEdgeCases:
    """Additional edge case tests for trust analytics."""

    def test_overview_generated_at_is_recent(self, tmp_path: Path) -> None:
        """generated_at timestamp is approximately now."""
        registry, trust_manager, _ = _make_registry(tmp_path, pack_names=[])
        svc = TrustAnalyticsService(registry, trust_manager)
        overview = svc.get_overview()
        delta = (datetime.now(UTC) - overview.generated_at).total_seconds()
        assert delta < 5.0  # should be within 5 seconds

    def test_trust_chain_entry_model_fields(self) -> None:
        """TrustChainEntry model validates field types."""
        entry = TrustChainEntry(
            pack_name="test",
            version="1.0.0",
            trust_level="verified",
            signer_id="bot",
            signed_at=datetime.now(UTC),
            signature_valid=True,
            policy_decision="ALLOW",
        )
        assert entry.pack_name == "test"
        assert entry.signature_valid is True

    def test_trust_audit_record_model_fields(self) -> None:
        """TrustAuditRecord model validates field types."""
        record = TrustAuditRecord(
            pack_name="test-pack",
            event_type="install",
            timestamp=datetime.now(UTC),
            details={"version": "1.0.0"},
        )
        assert record.event_type == "install"
        assert record.details["version"] == "1.0.0"

    def test_overview_model_defaults(self) -> None:
        """TrustOverview default values are correct."""
        overview = TrustOverview()
        assert overview.total_packs == 0
        assert overview.signed_packs == 0
        assert overview.unsigned_packs == 0
        assert overview.by_trust_level == {}
        assert overview.signature_rate == 0.0
        assert overview.policy_compliant == 0
        assert overview.policy_violations == 0

    def test_dashboard_summary_model_defaults(self) -> None:
        """TrustDashboardSummary default values are correct."""
        summary = TrustDashboardSummary(
            overview=TrustOverview(),
            trust_chain=[],
            recent_audit=[],
        )
        assert summary.curation_stats is None
        assert summary.current_policy == {}

    def test_chain_entry_without_verification_key(self, tmp_path: Path) -> None:
        """Without verification key, chain entries have signature_valid=None."""
        registry, trust_manager, _ = _make_registry(
            tmp_path,
            pack_names=["no-key"],
            sign_names=["no-key"],
        )
        svc = TrustAnalyticsService(registry, trust_manager, verification_key="")
        chain = svc.get_trust_chain()
        assert chain[0].signature_valid is None
