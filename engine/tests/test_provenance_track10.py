"""Tests for Track 10: provenance receipts, audit export, runtime guard.

Covers:
- HashedReceipt model and SHA-256 hash computation
- ReceiptStore CRUD, entity/session queries, chain traversal, eviction
- ReceiptExporter JSON/CSV export with filters
- RuntimeGuard startup invariants and runtime info
- API route integration tests for all T10 endpoints
"""

from __future__ import annotations

import csv
import io
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.main import app
from agent33.ops.runtime_guard import RuntimeGuard, RuntimeInfo, StartupInvariant
from agent33.provenance.audit_export import (
    AuditExportRecord,
    ExportFilters,
    ExportFormat,
    ReceiptExporter,
)
from agent33.provenance.receipts import (
    EntityType,
    HashedReceipt,
    ReceiptStore,
    compute_hash,
)

# ---------------------------------------------------------------------------
# Hash computation tests
# ---------------------------------------------------------------------------


class TestComputeHash:
    def test_hash_of_dict(self) -> None:
        h = compute_hash({"key": "value"})
        assert len(h) == 64  # SHA-256 hex digest length
        # Deterministic
        assert h == compute_hash({"key": "value"})

    def test_hash_of_none_returns_empty(self) -> None:
        assert compute_hash(None) == ""

    def test_hash_of_empty_dict_returns_empty(self) -> None:
        assert compute_hash({}) == ""

    def test_hash_of_empty_list_returns_empty(self) -> None:
        assert compute_hash([]) == ""

    def test_hash_of_list(self) -> None:
        h = compute_hash([1, 2, 3])
        assert len(h) == 64
        assert h == compute_hash([1, 2, 3])

    def test_hash_is_order_independent_for_dict_keys(self) -> None:
        h1 = compute_hash({"a": 1, "b": 2})
        h2 = compute_hash({"b": 2, "a": 1})
        assert h1 == h2  # sort_keys=True ensures same hash

    def test_hash_differs_for_different_data(self) -> None:
        h1 = compute_hash({"x": 1})
        h2 = compute_hash({"x": 2})
        assert h1 != h2

    def test_hash_of_string(self) -> None:
        h = compute_hash("hello")
        assert len(h) == 64


# ---------------------------------------------------------------------------
# HashedReceipt model tests
# ---------------------------------------------------------------------------


class TestHashedReceipt:
    def test_default_fields(self) -> None:
        receipt = HashedReceipt(entity_type=EntityType.AGENT_ACTION)
        assert receipt.receipt_id  # non-empty UUID hex
        assert len(receipt.receipt_id) == 32
        assert receipt.entity_type == EntityType.AGENT_ACTION
        assert receipt.actor == ""
        assert receipt.tenant_id == ""
        assert receipt.inputs_hash == ""
        assert receipt.outputs_hash == ""
        assert receipt.parent_receipt_id == ""
        assert receipt.metadata == {}
        assert receipt.timestamp.tzinfo is not None

    @pytest.mark.parametrize("entity_type", list(EntityType))
    def test_each_entity_type(self, entity_type: EntityType) -> None:
        receipt = HashedReceipt(
            entity_type=entity_type,
            actor="test-actor",
            entity_id="entity-123",
        )
        assert receipt.entity_type == entity_type
        assert receipt.actor == "test-actor"
        assert receipt.entity_id == "entity-123"

    def test_with_hashes(self) -> None:
        inputs_hash = compute_hash({"prompt": "hello"})
        outputs_hash = compute_hash({"response": "world"})
        receipt = HashedReceipt(
            entity_type=EntityType.TOOL_CALL,
            inputs_hash=inputs_hash,
            outputs_hash=outputs_hash,
        )
        assert len(receipt.inputs_hash) == 64
        assert len(receipt.outputs_hash) == 64
        assert receipt.inputs_hash == inputs_hash
        assert receipt.outputs_hash == outputs_hash

    def test_with_metadata(self) -> None:
        receipt = HashedReceipt(
            entity_type=EntityType.DATA_ACCESS,
            metadata={"table": "users", "rows": 42},
        )
        assert receipt.metadata["table"] == "users"
        assert receipt.metadata["rows"] == 42


# ---------------------------------------------------------------------------
# ReceiptStore tests
# ---------------------------------------------------------------------------


class TestReceiptStore:
    def _make(
        self,
        entity_type: EntityType = EntityType.AGENT_ACTION,
        *,
        receipt_id: str = "",
        entity_id: str = "",
        parent_receipt_id: str = "",
        session_id: str = "",
        tenant_id: str = "",
        actor: str = "",
        ts: datetime | None = None,
    ) -> HashedReceipt:
        kwargs: dict = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "session_id": session_id,
            "tenant_id": tenant_id,
            "actor": actor,
            "parent_receipt_id": parent_receipt_id,
        }
        if receipt_id:
            kwargs["receipt_id"] = receipt_id
        if ts is not None:
            kwargs["timestamp"] = ts
        return HashedReceipt(**kwargs)

    def test_record_and_get(self) -> None:
        store = ReceiptStore(max_receipts=100)
        r = self._make(receipt_id="abc123")
        store.record(r)
        assert store.count == 1
        found = store.get("abc123")
        assert found is not None
        assert found.receipt_id == "abc123"

    def test_get_missing_returns_none(self) -> None:
        store = ReceiptStore(max_receipts=100)
        assert store.get("nonexistent") is None

    def test_list_by_entity(self) -> None:
        store = ReceiptStore()
        store.record(self._make(EntityType.TOOL_CALL, entity_id="shell", receipt_id="r1"))
        store.record(self._make(EntityType.TOOL_CALL, entity_id="web_fetch", receipt_id="r2"))
        store.record(self._make(EntityType.TOOL_CALL, entity_id="shell", receipt_id="r3"))

        results = store.list_by_entity(EntityType.TOOL_CALL, "shell")
        assert len(results) == 2
        assert all(r.entity_id == "shell" for r in results)
        # Newest first
        assert results[0].receipt_id == "r3"
        assert results[1].receipt_id == "r1"

    def test_list_by_session(self) -> None:
        store = ReceiptStore()
        store.record(self._make(session_id="s1", receipt_id="r1"))
        store.record(self._make(session_id="s2", receipt_id="r2"))
        store.record(self._make(session_id="s1", receipt_id="r3"))

        results = store.list_by_session("s1")
        assert len(results) == 2
        assert all(r.session_id == "s1" for r in results)

    def test_list_all_by_entity_type(self) -> None:
        store = ReceiptStore()
        store.record(self._make(EntityType.AGENT_ACTION))
        store.record(self._make(EntityType.TOOL_CALL))
        store.record(self._make(EntityType.AGENT_ACTION))

        results = store.list_all(entity_type=EntityType.AGENT_ACTION)
        assert len(results) == 2
        assert all(r.entity_type == EntityType.AGENT_ACTION for r in results)

    def test_list_all_by_actor(self) -> None:
        store = ReceiptStore()
        store.record(self._make(actor="alice"))
        store.record(self._make(actor="bob"))

        results = store.list_all(actor="alice")
        assert len(results) == 1
        assert results[0].actor == "alice"

    def test_list_all_since_datetime(self) -> None:
        store = ReceiptStore()
        old = datetime(2024, 1, 1, tzinfo=UTC)
        recent = datetime(2026, 1, 1, tzinfo=UTC)
        store.record(self._make(ts=old))
        store.record(self._make(ts=recent))

        cutoff = datetime(2025, 6, 1, tzinfo=UTC)
        results = store.list_all(since=cutoff)
        assert len(results) == 1
        assert results[0].timestamp == recent

    def test_list_all_until_datetime(self) -> None:
        store = ReceiptStore()
        old = datetime(2024, 1, 1, tzinfo=UTC)
        recent = datetime(2026, 1, 1, tzinfo=UTC)
        store.record(self._make(ts=old))
        store.record(self._make(ts=recent))

        cutoff = datetime(2025, 1, 1, tzinfo=UTC)
        results = store.list_all(until=cutoff)
        assert len(results) == 1
        assert results[0].timestamp == old

    def test_list_all_limit(self) -> None:
        store = ReceiptStore()
        for _ in range(10):
            store.record(self._make())
        results = store.list_all(limit=3)
        assert len(results) == 3

    def test_list_all_returns_newest_first(self) -> None:
        store = ReceiptStore()
        t1 = datetime(2026, 1, 1, tzinfo=UTC)
        t2 = datetime(2026, 6, 1, tzinfo=UTC)
        store.record(self._make(ts=t1, receipt_id="older"))
        store.record(self._make(ts=t2, receipt_id="newer"))

        results = store.list_all()
        assert results[0].receipt_id == "newer"
        assert results[1].receipt_id == "older"

    def test_max_receipts_eviction(self) -> None:
        store = ReceiptStore(max_receipts=3)
        for i in range(4):
            store.record(self._make(receipt_id=f"r{i}"))

        assert store.count == 3
        assert store.get("r0") is None  # evicted
        assert store.get("r3") is not None

    def test_get_chain_3_deep(self) -> None:
        store = ReceiptStore()
        store.record(self._make(receipt_id="root", parent_receipt_id=""))
        store.record(self._make(receipt_id="mid", parent_receipt_id="root"))
        store.record(self._make(receipt_id="leaf", parent_receipt_id="mid"))

        chain = store.get_chain("leaf")
        assert len(chain) == 3
        assert chain[0].receipt_id == "leaf"
        assert chain[1].receipt_id == "mid"
        assert chain[2].receipt_id == "root"

    def test_get_chain_circular_stops(self) -> None:
        store = ReceiptStore()
        store.record(self._make(receipt_id="a", parent_receipt_id="b"))
        store.record(self._make(receipt_id="b", parent_receipt_id="a"))

        chain = store.get_chain("a")
        assert len(chain) == 2
        ids = {c.receipt_id for c in chain}
        assert ids == {"a", "b"}

    def test_get_chain_missing_parent_stops(self) -> None:
        store = ReceiptStore()
        store.record(self._make(receipt_id="child", parent_receipt_id="nonexistent"))

        chain = store.get_chain("child")
        assert len(chain) == 1
        assert chain[0].receipt_id == "child"

    def test_get_chain_nonexistent_receipt(self) -> None:
        store = ReceiptStore()
        chain = store.get_chain("nonexistent")
        assert chain == []


# ---------------------------------------------------------------------------
# ReceiptExporter tests
# ---------------------------------------------------------------------------


class TestReceiptExporter:
    def _populated_store(self) -> ReceiptStore:
        store = ReceiptStore()
        store.record(
            HashedReceipt(
                receipt_id="r1",
                entity_type=EntityType.AGENT_ACTION,
                entity_id="agent-001",
                actor="alice",
                action="invoke",
                inputs_hash=compute_hash({"prompt": "hello"}),
                outputs_hash=compute_hash({"response": "world"}),
                session_id="sess-1",
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        store.record(
            HashedReceipt(
                receipt_id="r2",
                entity_type=EntityType.TOOL_CALL,
                entity_id="shell",
                actor="bob",
                action="execute",
                session_id="sess-1",
                timestamp=datetime(2026, 3, 1, tzinfo=UTC),
            )
        )
        store.record(
            HashedReceipt(
                receipt_id="r3",
                entity_type=EntityType.DATA_ACCESS,
                entity_id="db-table",
                actor="alice",
                action="read",
                session_id="sess-2",
                timestamp=datetime(2026, 6, 1, tzinfo=UTC),
            )
        )
        return store

    def test_export_json_all(self) -> None:
        store = self._populated_store()
        exporter = ReceiptExporter(store)
        record = exporter.export_json()

        assert isinstance(record, AuditExportRecord)
        assert record.format == ExportFormat.JSON
        assert record.receipt_count == 3
        assert len(record.export_id) == 32

        # Parse the JSON data to verify structure
        data = json.loads(record.data)
        assert len(data) == 3
        assert data[0]["receipt_id"] == "r3"  # newest first

    def test_export_json_filter_by_actor(self) -> None:
        store = self._populated_store()
        exporter = ReceiptExporter(store)
        record = exporter.export_json(ExportFilters(actor="alice"))

        assert record.receipt_count == 2
        data = json.loads(record.data)
        assert all(r["actor"] == "alice" for r in data)

    def test_export_json_filter_by_entity_type(self) -> None:
        store = self._populated_store()
        exporter = ReceiptExporter(store)
        record = exporter.export_json(ExportFilters(entity_type="tool_call"))

        assert record.receipt_count == 1
        data = json.loads(record.data)
        assert data[0]["entity_type"] == "tool_call"

    def test_export_json_filter_by_date_range(self) -> None:
        store = self._populated_store()
        exporter = ReceiptExporter(store)
        record = exporter.export_json(
            ExportFilters(
                since=datetime(2026, 2, 1, tzinfo=UTC),
                until=datetime(2026, 4, 1, tzinfo=UTC),
            )
        )

        assert record.receipt_count == 1
        data = json.loads(record.data)
        assert data[0]["receipt_id"] == "r2"

    def test_export_json_filter_by_session(self) -> None:
        store = self._populated_store()
        exporter = ReceiptExporter(store)
        record = exporter.export_json(ExportFilters(session_id="sess-1"))

        assert record.receipt_count == 2
        data = json.loads(record.data)
        assert all(r["session_id"] == "sess-1" for r in data)

    def test_export_csv_all(self) -> None:
        store = self._populated_store()
        exporter = ReceiptExporter(store)
        record = exporter.export_csv()

        assert record.format == ExportFormat.CSV
        assert record.receipt_count == 3

        # Parse CSV to verify headers and row count
        reader = csv.DictReader(io.StringIO(record.data))
        rows = list(reader)
        assert len(rows) == 3
        assert "receipt_id" in rows[0]
        assert "entity_type" in rows[0]
        assert "inputs_hash" in rows[0]
        assert "outputs_hash" in rows[0]

    def test_export_csv_filter_by_actor(self) -> None:
        store = self._populated_store()
        exporter = ReceiptExporter(store)
        record = exporter.export_csv(ExportFilters(actor="bob"))

        reader = csv.DictReader(io.StringIO(record.data))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["actor"] == "bob"

    def test_get_export(self) -> None:
        store = self._populated_store()
        exporter = ReceiptExporter(store)
        record = exporter.export_json()

        retrieved = exporter.get_export(record.export_id)
        assert retrieved is not None
        assert retrieved.export_id == record.export_id
        assert retrieved.receipt_count == record.receipt_count

    def test_get_export_missing(self) -> None:
        store = ReceiptStore()
        exporter = ReceiptExporter(store)
        assert exporter.get_export("nonexistent") is None

    def test_export_empty_store(self) -> None:
        store = ReceiptStore()
        exporter = ReceiptExporter(store)
        record = exporter.export_json()
        assert record.receipt_count == 0
        data = json.loads(record.data)
        assert data == []


# ---------------------------------------------------------------------------
# RuntimeGuard tests
# ---------------------------------------------------------------------------


class TestRuntimeGuard:
    def _make_app_state(self, **attrs: object) -> SimpleNamespace:
        """Create a fake app.state with optional attributes."""
        return SimpleNamespace(**attrs)

    def test_all_required_present(self) -> None:
        state = self._make_app_state(
            agent_registry="registry",
            tool_registry="tools",
            model_router="router",
            provenance_collector="collector",
            receipt_store="store",
            skill_registry="skills",
        )
        guard = RuntimeGuard(state, start_time=time.time())
        invariants = guard.check_startup_invariants()

        assert len(invariants) == 6
        assert all(inv.present for inv in invariants)
        for inv in invariants:
            assert "initialised" in inv.message

    def test_required_missing(self) -> None:
        state = self._make_app_state(
            # Missing agent_registry, tool_registry, model_router
            provenance_collector="collector",
        )
        guard = RuntimeGuard(state, start_time=time.time())
        invariants = guard.check_startup_invariants()

        required_missing = [inv for inv in invariants if inv.required and not inv.present]
        assert len(required_missing) == 3  # agent_registry, tool_registry, model_router
        for inv in required_missing:
            assert "MISSING" in inv.message

    def test_optional_missing_not_flagged_as_error(self) -> None:
        state = self._make_app_state(
            agent_registry="registry",
            tool_registry="tools",
            model_router="router",
        )
        guard = RuntimeGuard(state, start_time=time.time())
        invariants = guard.check_startup_invariants()

        optional_missing = [inv for inv in invariants if not inv.required and not inv.present]
        assert len(optional_missing) == 3  # provenance_collector, receipt_store, skill_registry
        for inv in optional_missing:
            assert "optional" in inv.message

    def test_extra_invariants(self) -> None:
        state = self._make_app_state(
            agent_registry="registry",
            tool_registry="tools",
            model_router="router",
            custom_service="present",
        )
        guard = RuntimeGuard(
            state,
            start_time=time.time(),
            extra_invariants=[("custom_service", "Custom Service", True)],
        )
        invariants = guard.check_startup_invariants()

        custom = [inv for inv in invariants if inv.name == "custom_service"]
        assert len(custom) == 1
        assert custom[0].present is True

    def test_graceful_shutdown_mirrors_startup(self) -> None:
        state = self._make_app_state(
            agent_registry="registry",
            tool_registry="tools",
            model_router="router",
        )
        guard = RuntimeGuard(state, start_time=time.time())

        startup = guard.check_startup_invariants()
        shutdown = guard.check_graceful_shutdown()
        assert len(startup) == len(shutdown)
        for s, sh in zip(startup, shutdown, strict=True):
            assert s.name == sh.name
            assert s.present == sh.present

    def test_get_runtime_info(self) -> None:
        state = self._make_app_state(
            agent_registry="registry",
            tool_registry="tools",
            model_router="router",
        )
        start = time.time() - 10  # 10 seconds ago
        guard = RuntimeGuard(state, start_time=start)
        info = guard.get_runtime_info()

        assert isinstance(info, RuntimeInfo)
        assert info.pid > 0
        assert info.uptime_seconds >= 10.0
        assert info.python_version  # non-empty
        assert info.platform  # non-empty
        assert info.all_invariants_ok is True  # all required are present
        assert len(info.invariants) == 6

    def test_get_runtime_info_required_missing(self) -> None:
        state = self._make_app_state()  # nothing present
        guard = RuntimeGuard(state, start_time=time.time())
        info = guard.get_runtime_info()

        assert info.all_invariants_ok is False


# ---------------------------------------------------------------------------
# StartupInvariant model tests
# ---------------------------------------------------------------------------


class TestStartupInvariant:
    def test_default_values(self) -> None:
        inv = StartupInvariant(name="test")
        assert inv.name == "test"
        assert inv.required is True
        assert inv.present is False
        assert inv.message == ""

    def test_custom_values(self) -> None:
        inv = StartupInvariant(
            name="agent_registry",
            required=True,
            present=True,
            message="Agent Registry initialised",
        )
        assert inv.present is True
        assert "initialised" in inv.message


# ---------------------------------------------------------------------------
# API route integration tests
# ---------------------------------------------------------------------------


def _auth_headers(
    scopes: list[str] | None = None,
) -> dict[str, str]:
    """Build a valid JWT for route testing."""
    import jwt

    from agent33.config import settings

    payload = {
        "sub": "test-user",
        "tenant_id": "test-tenant",
        "scopes": scopes
        or [
            "admin",
            "provenance:read",
            "provenance:export",
            "operator:read",
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
def _install_t10_services() -> None:
    """Install T10 provenance services on app.state for route tests."""
    from agent33.provenance.audit_export import ReceiptExporter
    from agent33.provenance.collector import ProvenanceCollector
    from agent33.provenance.timeline import AuditTimelineService

    # Original services (needed for existing endpoints)
    collector = ProvenanceCollector(max_receipts=1000)
    app.state.provenance_collector = collector
    app.state.audit_timeline_service = AuditTimelineService(collector)

    from agent33.provenance.audit_export import AuditExporter

    app.state.audit_exporter = AuditExporter(collector)

    from agent33.runtime.version import RuntimeVersionInfo

    app.state.runtime_version_info = RuntimeVersionInfo(
        version="0.99.0",
        git_short_hash="deadbeef",
        python_version="3.11.0",
        platform="test-platform",
    )

    # T10 services
    store = ReceiptStore(max_receipts=1000)
    store.record(
        HashedReceipt(
            receipt_id="t10-r1",
            entity_type=EntityType.AGENT_ACTION,
            entity_id="agent-001",
            actor="test-user",
            action="invoke",
            inputs_hash=compute_hash({"prompt": "hello"}),
            outputs_hash=compute_hash({"response": "world"}),
            session_id="sess-t10",
            tenant_id="test-tenant",
        )
    )
    store.record(
        HashedReceipt(
            receipt_id="t10-r2",
            entity_type=EntityType.TOOL_CALL,
            entity_id="shell",
            actor="test-user",
            action="execute",
            session_id="sess-t10",
            parent_receipt_id="t10-r1",
            tenant_id="test-tenant",
        )
    )
    store.record(
        HashedReceipt(
            receipt_id="t10-r3",
            entity_type=EntityType.WORKFLOW_STEP,
            entity_id="step-5",
            actor="scheduler",
            action="run",
            session_id="sess-other",
            parent_receipt_id="t10-r2",
            tenant_id="test-tenant",
        )
    )

    exporter = ReceiptExporter(store)
    app.state.receipt_store = store
    app.state.receipt_exporter = exporter

    # Runtime guard
    app.state.agent_registry = "mock-registry"
    app.state.tool_registry = "mock-tools"
    app.state.model_router = "mock-router"
    app.state.start_time = time.time() - 60
    guard = RuntimeGuard(app.state, start_time=app.state.start_time)
    app.state.runtime_guard = guard


@pytest.mark.usefixtures("_install_t10_services")
class TestHashedReceiptAPI:
    """Route tests for /v1/provenance/hashed-receipts endpoints."""

    async def test_list_hashed_receipts(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/hashed-receipts")

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 3
        assert len(body["receipts"]) == 3
        r = body["receipts"][0]
        assert "receipt_id" in r
        assert "entity_type" in r
        assert "inputs_hash" in r
        assert "outputs_hash" in r

    async def test_list_hashed_receipts_filter_by_entity_type(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get(
                "/v1/provenance/hashed-receipts",
                params={"entity_type": "tool_call"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["receipts"][0]["entity_type"] == "tool_call"

    async def test_list_hashed_receipts_filter_by_session(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get(
                "/v1/provenance/hashed-receipts",
                params={"session_id": "sess-t10"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 2
        assert all(r["session_id"] == "sess-t10" for r in body["receipts"])

    async def test_list_hashed_receipts_filter_by_actor(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get(
                "/v1/provenance/hashed-receipts",
                params={"actor": "scheduler"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["count"] == 1
        assert body["receipts"][0]["actor"] == "scheduler"

    async def test_get_hashed_receipt(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/hashed-receipts/t10-r1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["receipt_id"] == "t10-r1"
        assert body["entity_type"] == "agent_action"
        assert body["actor"] == "test-user"
        assert body["action"] == "invoke"
        assert body["inputs_hash"]  # non-empty
        assert body["outputs_hash"]  # non-empty

    async def test_get_hashed_receipt_not_found(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/hashed-receipts/nonexistent")

        assert resp.status_code == 404

    async def test_get_hashed_receipt_chain(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/hashed-receipts/t10-r3/chain")

        assert resp.status_code == 200
        body = resp.json()
        assert body["length"] == 3
        assert len(body["chain"]) == 3
        assert body["chain"][0]["receipt_id"] == "t10-r3"
        assert body["chain"][1]["receipt_id"] == "t10-r2"
        assert body["chain"][2]["receipt_id"] == "t10-r1"

    async def test_get_chain_not_found(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/hashed-receipts/nonexistent/chain")

        assert resp.status_code == 404

    async def test_hashed_receipts_require_auth(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/v1/provenance/hashed-receipts")

        assert resp.status_code == 401


@pytest.mark.usefixtures("_install_t10_services")
class TestHashedExportAPI:
    """Route tests for /v1/provenance/hashed-export endpoints."""

    async def test_export_json(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.post(
                "/v1/provenance/hashed-export",
                json={"format": "json"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["format"] == "json"
        assert body["receipt_count"] == 3
        assert body["export_id"]

        # Verify JSON data is valid
        data = json.loads(body["data"])
        assert len(data) == 3

    async def test_export_csv(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.post(
                "/v1/provenance/hashed-export",
                json={"format": "csv"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["format"] == "csv"
        assert body["receipt_count"] == 3

        # Verify CSV data is valid
        reader = csv.DictReader(io.StringIO(body["data"]))
        rows = list(reader)
        assert len(rows) == 3
        assert "receipt_id" in rows[0]

    async def test_export_with_filters(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.post(
                "/v1/provenance/hashed-export",
                json={"format": "json", "actor": "scheduler"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["receipt_count"] == 1
        data = json.loads(body["data"])
        assert data[0]["actor"] == "scheduler"

    async def test_get_export_by_id(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            # First create an export
            create_resp = await client.post(
                "/v1/provenance/hashed-export",
                json={"format": "json"},
            )
            export_id = create_resp.json()["export_id"]

            # Then retrieve it
            resp = await client.get(
                f"/v1/provenance/hashed-export/{export_id}",
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["export_id"] == export_id
        assert body["receipt_count"] == 3

    async def test_get_export_not_found(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/provenance/hashed-export/nonexistent")

        assert resp.status_code == 404

    async def test_export_requires_auth(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/v1/provenance/hashed-export",
                json={"format": "json"},
            )

        assert resp.status_code == 401


@pytest.mark.usefixtures("_install_t10_services")
class TestOpsRuntimeAPI:
    """Route tests for /v1/ops/runtime endpoint."""

    async def test_runtime_info(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/ops/runtime")

        assert resp.status_code == 200
        body = resp.json()
        assert body["pid"] > 0
        assert body["uptime_seconds"] >= 0
        assert body["python_version"]
        assert body["platform"]
        assert isinstance(body["invariants"], list)
        assert len(body["invariants"]) > 0
        assert body["all_invariants_ok"] is True

        # Verify invariant shape
        inv = body["invariants"][0]
        assert "name" in inv
        assert "required" in inv
        assert "present" in inv
        assert "message" in inv

    async def test_runtime_info_requires_auth(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            resp = await client.get("/v1/ops/runtime")

        assert resp.status_code == 401

    async def test_runtime_info_requires_operator_scope(self) -> None:
        """Verify that provenance:read alone is insufficient."""
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(scopes=["provenance:read"]),
        ) as client:
            resp = await client.get("/v1/ops/runtime")

        assert resp.status_code == 403
