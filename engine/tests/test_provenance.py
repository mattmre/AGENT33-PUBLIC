"""Tests for provenance receipts, audit export, runtime version, and restart guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_settings import BaseSettings

from agent33.main import app
from agent33.provenance.audit_export import AuditExporter
from agent33.provenance.collector import ProvenanceCollector
from agent33.provenance.models import (
    AuditBundle,
    ProvenanceReceipt,
    ProvenanceSource,
)
from agent33.provenance.timeline import AuditTimelineService
from agent33.runtime.restart_guard import RestartGuard
from agent33.runtime.version import RuntimeVersionInfo, resolve_version

# ---------------------------------------------------------------------------
# Receipt model tests
# ---------------------------------------------------------------------------


class TestProvenanceReceipt:
    def test_receipt_default_fields(self) -> None:
        receipt = ProvenanceReceipt(source=ProvenanceSource.SESSION_SPAWN)
        assert receipt.receipt_id  # non-empty UUID hex
        assert len(receipt.receipt_id) == 32
        assert receipt.source == ProvenanceSource.SESSION_SPAWN
        assert receipt.actor == ""
        assert receipt.tenant_id == ""
        assert receipt.parent_receipt_id == ""
        assert receipt.metadata == {}
        assert receipt.timestamp.tzinfo is not None

    @pytest.mark.parametrize("source", list(ProvenanceSource))
    def test_receipt_with_each_source(self, source: ProvenanceSource) -> None:
        receipt = ProvenanceReceipt(
            source=source,
            actor="test-actor",
            tenant_id="tenant-1",
        )
        assert receipt.source == source
        assert receipt.actor == "test-actor"
        assert receipt.source.value.count(".") == 1  # all sources are "category.action"

    def test_receipt_with_metadata(self) -> None:
        receipt = ProvenanceReceipt(
            source=ProvenanceSource.TOOL_EXECUTION,
            metadata={"tool_id": "shell", "duration_ms": 42},
        )
        assert receipt.metadata["tool_id"] == "shell"
        assert receipt.metadata["duration_ms"] == 42


# ---------------------------------------------------------------------------
# Collector tests
# ---------------------------------------------------------------------------


class TestProvenanceCollector:
    def _make_receipt(
        self,
        source: ProvenanceSource = ProvenanceSource.SESSION_SPAWN,
        *,
        receipt_id: str = "",
        parent_receipt_id: str = "",
        session_id: str = "",
        tenant_id: str = "",
        actor: str = "",
        ts: datetime | None = None,
        metadata: dict | None = None,
    ) -> ProvenanceReceipt:
        kwargs: dict = {
            "source": source,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "actor": actor,
            "parent_receipt_id": parent_receipt_id,
            "metadata": metadata or {},
        }
        if receipt_id:
            kwargs["receipt_id"] = receipt_id
        if ts is not None:
            kwargs["timestamp"] = ts
        return ProvenanceReceipt(**kwargs)

    def test_record_and_get(self) -> None:
        collector = ProvenanceCollector(max_receipts=100)
        r = self._make_receipt(receipt_id="abc123")
        collector.record(r)
        assert collector.count == 1
        found = collector.get("abc123")
        assert found is not None
        assert found.receipt_id == "abc123"

    def test_get_missing_returns_none(self) -> None:
        collector = ProvenanceCollector(max_receipts=100)
        assert collector.get("nonexistent") is None

    def test_query_by_source(self) -> None:
        collector = ProvenanceCollector()
        collector.record(self._make_receipt(ProvenanceSource.SESSION_SPAWN))
        collector.record(self._make_receipt(ProvenanceSource.TOOL_EXECUTION))
        collector.record(self._make_receipt(ProvenanceSource.SESSION_SPAWN))

        results = collector.query(source=ProvenanceSource.SESSION_SPAWN)
        assert len(results) == 2
        assert all(r.source == ProvenanceSource.SESSION_SPAWN for r in results)

    def test_query_by_session_id(self) -> None:
        collector = ProvenanceCollector()
        collector.record(self._make_receipt(session_id="s1"))
        collector.record(self._make_receipt(session_id="s2"))
        collector.record(self._make_receipt(session_id="s1"))

        results = collector.query(session_id="s1")
        assert len(results) == 2
        assert all(r.session_id == "s1" for r in results)

    def test_query_by_tenant_id(self) -> None:
        collector = ProvenanceCollector()
        collector.record(self._make_receipt(tenant_id="t1"))
        collector.record(self._make_receipt(tenant_id="t2"))

        results = collector.query(tenant_id="t1")
        assert len(results) == 1
        assert results[0].tenant_id == "t1"

    def test_query_since_datetime(self) -> None:
        collector = ProvenanceCollector()
        old = datetime(2024, 1, 1, tzinfo=UTC)
        recent = datetime(2026, 1, 1, tzinfo=UTC)
        collector.record(self._make_receipt(ts=old))
        collector.record(self._make_receipt(ts=recent))

        cutoff = datetime(2025, 6, 1, tzinfo=UTC)
        results = collector.query(since=cutoff)
        assert len(results) == 1
        assert results[0].timestamp == recent

    def test_query_limit(self) -> None:
        collector = ProvenanceCollector()
        for _ in range(10):
            collector.record(self._make_receipt())

        results = collector.query(limit=3)
        assert len(results) == 3

    def test_query_returns_newest_first(self) -> None:
        collector = ProvenanceCollector()
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 6, 1, tzinfo=UTC)
        collector.record(self._make_receipt(ts=t1, receipt_id="older"))
        collector.record(self._make_receipt(ts=t2, receipt_id="newer"))

        results = collector.query()
        assert results[0].receipt_id == "newer"
        assert results[1].receipt_id == "older"

    def test_max_receipts_eviction(self) -> None:
        collector = ProvenanceCollector(max_receipts=3)
        r1 = self._make_receipt(receipt_id="r1")
        r2 = self._make_receipt(receipt_id="r2")
        r3 = self._make_receipt(receipt_id="r3")
        r4 = self._make_receipt(receipt_id="r4")

        collector.record(r1)
        collector.record(r2)
        collector.record(r3)
        assert collector.count == 3

        collector.record(r4)
        assert collector.count == 3
        # r1 should be evicted
        assert collector.get("r1") is None
        assert collector.get("r4") is not None

    def test_build_chain_3_deep(self) -> None:
        collector = ProvenanceCollector()
        r1 = self._make_receipt(receipt_id="root", parent_receipt_id="")
        r2 = self._make_receipt(receipt_id="mid", parent_receipt_id="root")
        r3 = self._make_receipt(receipt_id="leaf", parent_receipt_id="mid")
        collector.record(r1)
        collector.record(r2)
        collector.record(r3)

        chain = collector.build_chain("leaf")
        assert len(chain) == 3
        assert chain[0].receipt_id == "leaf"
        assert chain[1].receipt_id == "mid"
        assert chain[2].receipt_id == "root"

    def test_build_chain_circular_stops(self) -> None:
        collector = ProvenanceCollector()
        # Create a cycle: a -> b -> a
        r1 = self._make_receipt(receipt_id="a", parent_receipt_id="b")
        r2 = self._make_receipt(receipt_id="b", parent_receipt_id="a")
        collector.record(r1)
        collector.record(r2)

        chain = collector.build_chain("a")
        # Should stop at 2, not loop infinitely
        assert len(chain) == 2
        ids = {c.receipt_id for c in chain}
        assert ids == {"a", "b"}

    def test_build_chain_missing_parent_stops(self) -> None:
        collector = ProvenanceCollector()
        r1 = self._make_receipt(receipt_id="child", parent_receipt_id="nonexistent")
        collector.record(r1)

        chain = collector.build_chain("child")
        assert len(chain) == 1
        assert chain[0].receipt_id == "child"


# ---------------------------------------------------------------------------
# Timeline tests
# ---------------------------------------------------------------------------


class TestAuditTimeline:
    def test_timeline_build_produces_summaries(self) -> None:
        collector = ProvenanceCollector()
        collector.record(
            ProvenanceReceipt(
                source=ProvenanceSource.TOOL_EXECUTION,
                actor="user-1",
                metadata={"tool_id": "shell"},
            )
        )
        collector.record(
            ProvenanceReceipt(
                source=ProvenanceSource.SESSION_SPAWN,
                actor="user-2",
                metadata={"name": "research-session"},
            )
        )

        svc = AuditTimelineService(collector)
        entries = svc.build()

        assert len(entries) == 2
        # Newest first
        assert entries[0].source == ProvenanceSource.SESSION_SPAWN
        assert "research-session" in entries[0].summary
        assert entries[0].actor == "user-2"

        assert entries[1].source == ProvenanceSource.TOOL_EXECUTION
        assert "shell" in entries[1].summary

    def test_timeline_empty_metadata_still_produces_summary(self) -> None:
        collector = ProvenanceCollector()
        collector.record(ProvenanceReceipt(source=ProvenanceSource.CONFIG_CHANGE, actor="admin"))

        svc = AuditTimelineService(collector)
        entries = svc.build()
        assert len(entries) == 1
        assert entries[0].summary == "Config Change"  # no metadata detail

    def test_timeline_filters_by_tenant(self) -> None:
        collector = ProvenanceCollector()
        collector.record(ProvenanceReceipt(source=ProvenanceSource.BACKUP_CREATE, tenant_id="t1"))
        collector.record(ProvenanceReceipt(source=ProvenanceSource.BACKUP_CREATE, tenant_id="t2"))

        svc = AuditTimelineService(collector)
        entries = svc.build(tenant_id="t1")
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# Audit export tests
# ---------------------------------------------------------------------------


class TestAuditExport:
    def test_export_creates_bundle_with_correct_shape(self) -> None:
        collector = ProvenanceCollector()
        collector.record(
            ProvenanceReceipt(
                source=ProvenanceSource.PACK_INSTALL,
                actor="admin",
                metadata={"name": "llm-tools"},
            )
        )
        collector.record(
            ProvenanceReceipt(
                source=ProvenanceSource.WORKFLOW_RUN,
                actor="scheduler",
                metadata={"summary": "nightly-build"},
            )
        )

        exporter = AuditExporter(collector)
        bundle = exporter.export()

        assert isinstance(bundle, AuditBundle)
        assert len(bundle.bundle_id) == 32
        assert bundle.total_entries == 2
        assert len(bundle.entries) == 2
        assert bundle.export_format == "json"
        assert bundle.created_at.tzinfo is not None

    def test_export_respects_until_filter(self) -> None:
        collector = ProvenanceCollector()
        old = datetime(2024, 1, 1, tzinfo=UTC)
        new = datetime(2026, 6, 1, tzinfo=UTC)
        collector.record(
            ProvenanceReceipt(
                source=ProvenanceSource.SESSION_SPAWN,
                timestamp=old,
            )
        )
        collector.record(
            ProvenanceReceipt(
                source=ProvenanceSource.SESSION_SPAWN,
                timestamp=new,
            )
        )

        exporter = AuditExporter(collector)
        bundle = exporter.export(until=datetime(2025, 1, 1, tzinfo=UTC))

        assert bundle.total_entries == 1
        assert bundle.entries[0].timestamp == old


# ---------------------------------------------------------------------------
# RuntimeVersionInfo tests
# ---------------------------------------------------------------------------


class TestRuntimeVersion:
    def test_resolve_version_contains_python_version(self) -> None:
        info = resolve_version()
        assert info.python_version  # non-empty
        assert "." in info.python_version  # e.g. "3.11.x"

    def test_resolve_version_contains_platform(self) -> None:
        info = resolve_version()
        assert info.platform  # e.g. "win32" or "linux"

    def test_resolve_version_git_missing_graceful(self) -> None:
        with patch("agent33.runtime.version.subprocess.run", side_effect=FileNotFoundError):
            info = resolve_version()
        assert info.git_short_hash == ""
        assert info.python_version  # should still have the rest

    def test_resolve_version_git_nonzero_exit(self) -> None:
        mock_result = SimpleNamespace(returncode=128, stdout="", stderr="not a git repo")
        with patch("agent33.runtime.version.subprocess.run", return_value=mock_result):
            info = resolve_version()
        assert info.git_short_hash == ""

    def test_runtime_version_info_model(self) -> None:
        info = RuntimeVersionInfo(
            version="1.2.3",
            git_short_hash="abc1234",
            python_version="3.11.5",
            platform="linux",
        )
        assert info.version == "1.2.3"
        assert info.git_short_hash == "abc1234"


# ---------------------------------------------------------------------------
# RestartGuard tests
# ---------------------------------------------------------------------------


class _DummySettings(BaseSettings):
    """Minimal settings for restart guard testing."""

    model_config = {"env_prefix": "DUMMY_", "extra": "ignore"}

    name: str = "default"
    count: int = 5


class TestRestartGuard:
    def test_valid_changes_pass(self) -> None:
        guard = RestartGuard(_DummySettings)
        ok, errors = guard.validate_before_restart({"name": "new-name", "count": 10})
        assert ok is True
        assert errors == []

    def test_empty_changes_pass(self) -> None:
        guard = RestartGuard(_DummySettings)
        ok, errors = guard.validate_before_restart(None)
        assert ok is True
        assert errors == []

    def test_invalid_type_fails(self) -> None:
        guard = RestartGuard(_DummySettings)
        ok, errors = guard.validate_before_restart({"count": "not-an-int"})
        assert ok is False
        assert len(errors) >= 1
        # Error should mention the field
        assert any("count" in e.lower() for e in errors)

    def test_extra_fields_ignored(self) -> None:
        guard = RestartGuard(_DummySettings)
        ok, errors = guard.validate_before_restart({"unknown_field": "value"})
        assert ok is True
        assert errors == []


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


def _auth_headers() -> dict[str, str]:
    """Build a valid JWT for route testing."""
    import jwt

    from agent33.config import settings

    payload = {
        "sub": "test-user",
        "tenant_id": "test-tenant",
        "scopes": [
            "admin",
            "provenance:read",
            "provenance:export",
        ],
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def _install_provenance_services() -> None:
    """Install provenance services on app.state for route tests."""
    collector = ProvenanceCollector(max_receipts=1000)
    timeline_svc = AuditTimelineService(collector)
    exporter = AuditExporter(collector)

    version_info = RuntimeVersionInfo(
        version="0.99.0",
        git_short_hash="deadbeef",
        python_version="3.11.0",
        platform="test-platform",
    )

    app.state.provenance_collector = collector
    app.state.audit_timeline_service = timeline_svc
    app.state.audit_exporter = exporter
    app.state.runtime_version_info = version_info

    # Pre-populate some receipts
    collector.record(
        ProvenanceReceipt(
            receipt_id="test-receipt-1",
            source=ProvenanceSource.SESSION_SPAWN,
            actor="test-user",
            tenant_id="test-tenant",
            metadata={"name": "my-session"},
        )
    )
    collector.record(
        ProvenanceReceipt(
            receipt_id="test-receipt-2",
            source=ProvenanceSource.TOOL_EXECUTION,
            actor="test-user",
            tenant_id="test-tenant",
            metadata={"tool_id": "shell"},
        )
    )


@pytest.mark.usefixtures("_install_provenance_services")
class TestProvenanceAPI:
    """Route-level tests exercising the actual endpoint handlers."""

    async def test_list_receipts(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/receipts")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert len(body["receipts"]) == 2
        # Verify receipt shape
        r = body["receipts"][0]
        assert "receipt_id" in r
        assert "source" in r
        assert "timestamp" in r

    async def test_list_receipts_filter_by_source(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get(
                "/v1/provenance/receipts",
                params={"source": "tool.execution"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["receipts"][0]["source"] == "tool.execution"

    async def test_get_receipt_by_id(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/receipts/test-receipt-1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["receipt_id"] == "test-receipt-1"
        assert body["source"] == "session.spawn"
        assert body["actor"] == "test-user"

    async def test_get_receipt_not_found(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/receipts/nonexistent")

        assert resp.status_code == 404

    async def test_timeline(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/timeline")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        entry = body["entries"][0]
        assert "timestamp" in entry
        assert "source" in entry
        assert "summary" in entry
        assert "receipt_id" in entry

    async def test_export(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.post(
                "/v1/provenance/export",
                json={"tenant_id": "test-tenant"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert "bundle_id" in body
        assert body["total_entries"] == 2
        assert body["export_format"] == "json"
        assert len(body["entries"]) == 2

    async def test_runtime_version(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/runtime/version")

        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == "0.99.0"
        assert body["git_short_hash"] == "deadbeef"
        assert body["python_version"] == "3.11.0"
        assert body["platform"] == "test-platform"

    async def test_receipts_require_auth(self) -> None:
        """Unauthenticated request returns 401."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/v1/provenance/receipts")

        assert resp.status_code == 401
