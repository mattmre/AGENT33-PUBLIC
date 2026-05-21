"""Tests for IngestionMailbox, TaskMetricsCollector, and the T8 API endpoints.

Test plan:
  MB-01  post() with event_type="candidate_asset" → asset routed through IntakePipeline,
         not present in subsequent drain()
  MB-02  post() with unknown event_type → event lands in inbox; drain() returns it
  MB-03  drain() clears inbox so second call returns empty list
  MB-04  heartbeat() returns correct shape with "status", "inbox_depth", "pipeline_healthy"
  MB-05  heartbeat() inbox_depth reflects queued events across tenants
  TM-01  TaskMetricsCollector.record() + summary() totals, success/failure counts, avg latency
  TM-02  summary() filtered by tenant_id returns only that tenant's records
  TM-03  reset() with tenant_id clears only that tenant's records
  TM-04  reset() without tenant_id clears all records
  TM-05  summary() avg_latency_ms is None when no latency values recorded
  TM-06  persisted metrics survive collector re-instantiation
  TM-07  cleanup_expired() removes expired persisted metrics
  API-01 POST /v1/ingestion/mailbox returns {"status": "accepted", "event_id": ...}
  API-02 POST /v1/ingestion/mailbox with candidate_asset event returns accepted and routes asset
  API-03 GET /v1/ingestion/mailbox/drain returns list (may be empty)
  API-04 GET /v1/ingestion/heartbeat is unauthenticated and returns correct shape
  API-05 GET /v1/ingestion/metrics returns summary shape
  API-06 POST /v1/ingestion/mailbox increments metrics for authenticated tenant
  API-07 POST /v1/ingestion/mailbox requires ingestion:write scope
  API-08 GET /v1/ingestion/mailbox/drain requires ingestion:read scope
  API-09 GET /v1/ingestion/metrics requires ingestion:read scope
  API-10 GET /v1/ingestion/metrics/history returns recent records
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import ingestion as ingestion_mod
from agent33.ingestion.intake import IntakePipeline
from agent33.ingestion.mailbox import IngestionMailbox
from agent33.ingestion.mailbox_persistence import MailboxInboxPersistence
from agent33.ingestion.metrics import TaskMetricsCollector
from agent33.ingestion.service import IngestionService
from agent33.main import app
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT = "tenant-mailbox-test"
_TEST_DB_DIR = Path(__file__).resolve().parents[1] / "test-results" / "mailbox-persistence"


def _client(scopes: list[str], *, tenant_id: str = _TENANT) -> TestClient:
    token = create_access_token("mailbox-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def _anon_client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures — isolate all module-level singletons for each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mailbox_db_path() -> Path:
    _TEST_DB_DIR.mkdir(parents=True, exist_ok=True)
    db_path = _TEST_DB_DIR / f"mailbox-{uuid4().hex}.sqlite3"
    yield db_path
    if db_path.exists():
        db_path.unlink()


@pytest.fixture(autouse=True)
def _isolate_ingestion_state() -> None:  # type: ignore[return]
    """Replace module-level singletons with fresh instances and remove
    app.state attributes so route helpers fall back to the module-level
    objects.  Restored after each test.
    """
    saved_svc = ingestion_mod._service
    saved_pipeline = ingestion_mod._intake_pipeline
    saved_mailbox = ingestion_mod._ingestion_mailbox
    saved_metrics = ingestion_mod._task_metrics

    fresh_svc = IngestionService()
    fresh_pipeline = IntakePipeline(fresh_svc)
    fresh_mailbox = IngestionMailbox(pipeline=fresh_pipeline)
    fresh_metrics = TaskMetricsCollector()

    ingestion_mod._service = fresh_svc
    ingestion_mod._intake_pipeline = fresh_pipeline
    ingestion_mod._ingestion_mailbox = fresh_mailbox
    ingestion_mod._task_metrics = fresh_metrics

    state_keys = (
        "ingestion_service",
        "intake_pipeline",
        "ingestion_mailbox",
        "task_metrics",
    )
    saved_state: dict[str, object] = {}
    for key in state_keys:
        if hasattr(app.state, key):
            saved_state[key] = getattr(app.state, key)
            delattr(app.state, key)

    yield

    ingestion_mod._service = saved_svc
    ingestion_mod._intake_pipeline = saved_pipeline
    ingestion_mod._ingestion_mailbox = saved_mailbox
    ingestion_mod._task_metrics = saved_metrics

    for key in state_keys:
        if key in saved_state:
            setattr(app.state, key, saved_state[key])
        elif hasattr(app.state, key):
            delattr(app.state, key)


# ---------------------------------------------------------------------------
# MB-01: candidate_asset events are routed, not in inbox
# ---------------------------------------------------------------------------


class TestMailboxCandidateRouting:
    """MB-01: candidate_asset events go to IntakePipeline, not the inbox."""

    def test_candidate_asset_not_in_drain(self) -> None:
        mock_pipeline = MagicMock(spec=IntakePipeline)
        mailbox = IngestionMailbox(pipeline=mock_pipeline)

        mailbox.post(
            {
                "event_type": "candidate_asset",
                "payload": {
                    "name": "test-skill",
                    "source_uri": "https://example.com/skill",
                    "confidence": "high",
                    "asset_type": "skill",
                    "tenant_id": _TENANT,
                },
            },
            sender="operator-1",
            tenant_id=_TENANT,
        )

        drained = mailbox.drain(_TENANT)
        assert drained == [], "candidate_asset events must not appear in inbox"

    def test_candidate_asset_calls_pipeline_submit(self) -> None:
        mock_pipeline = MagicMock(spec=IntakePipeline)
        mailbox = IngestionMailbox(pipeline=mock_pipeline)

        payload = {
            "name": "routed-skill",
            "source_uri": "https://example.com",
            "confidence": "medium",
            "asset_type": "skill",
        }
        mailbox.post(
            {"event_type": "candidate_asset", "payload": payload},
            sender="op",
            tenant_id=_TENANT,
        )

        mock_pipeline.submit.assert_called_once_with(payload, source="op", tenant_id=_TENANT)


# ---------------------------------------------------------------------------
# MB-02: unknown event_type lands in inbox
# ---------------------------------------------------------------------------


class TestMailboxUnknownEventType:
    """MB-02: Non-candidate_asset events are held in the inbox."""

    def test_unknown_event_in_inbox_after_post(self) -> None:
        svc = IngestionService()
        pipeline = IntakePipeline(svc)
        mailbox = IngestionMailbox(pipeline=pipeline)

        result = mailbox.post(
            {"event_type": "custom_metric", "payload": {"value": 42}},
            sender="system",
            tenant_id=_TENANT,
        )
        assert result["status"] == "accepted"

        drained = mailbox.drain(_TENANT)
        assert len(drained) == 1
        assert drained[0]["event_type"] == "custom_metric"
        assert drained[0]["payload"] == {"value": 42}
        assert drained[0]["sender"] == "system"
        assert drained[0]["tenant_id"] == _TENANT
        assert "received_at" in drained[0]
        assert "event_id" in drained[0]

    def test_event_id_is_uuid_str(self) -> None:
        mailbox = IngestionMailbox(pipeline=MagicMock(spec=IntakePipeline))
        result = mailbox.post(
            {"event_type": "ping", "payload": {}},
            sender="s",
            tenant_id="t1",
        )
        import uuid

        uuid.UUID(result["event_id"])  # raises ValueError if not valid UUID

    def test_persisted_events_survive_mailbox_reinstantiation(self, mailbox_db_path: Path) -> None:
        with closing(MailboxInboxPersistence(mailbox_db_path)) as persistence:
            mailbox = IngestionMailbox(
                pipeline=MagicMock(spec=IntakePipeline),
                persistence=persistence,
            )
            mailbox.post(
                {"event_type": "custom_metric", "payload": {"value": 42}},
                sender="system",
                tenant_id=_TENANT,
            )

        with closing(MailboxInboxPersistence(mailbox_db_path)) as rehydrated_persistence:
            rehydrated_mailbox = IngestionMailbox(
                pipeline=MagicMock(spec=IntakePipeline),
                persistence=rehydrated_persistence,
            )

            assert rehydrated_mailbox.heartbeat()["inbox_depth"] == 1
            drained = rehydrated_mailbox.drain(_TENANT)
            assert [event["event_type"] for event in drained] == ["custom_metric"]


# ---------------------------------------------------------------------------
# MB-03: drain() clears the inbox
# ---------------------------------------------------------------------------


class TestMailboxDrain:
    """MB-03: drain() clears inbox so second call returns empty list."""

    def test_drain_twice_second_is_empty(self) -> None:
        mailbox = IngestionMailbox(pipeline=MagicMock(spec=IntakePipeline))
        mailbox.post(
            {"event_type": "op_event", "payload": {}},
            sender="s",
            tenant_id=_TENANT,
        )

        first = mailbox.drain(_TENANT)
        second = mailbox.drain(_TENANT)

        assert len(first) == 1
        assert second == []

    def test_drain_only_clears_requested_tenant(self) -> None:
        mailbox = IngestionMailbox(pipeline=MagicMock(spec=IntakePipeline))
        mailbox.post({"event_type": "e", "payload": {}}, sender="s", tenant_id="t-a")
        mailbox.post({"event_type": "e", "payload": {}}, sender="s", tenant_id="t-b")

        mailbox.drain("t-a")
        assert mailbox.drain("t-b") != []

    def test_persisted_drain_returns_oldest_first_and_clears_records(
        self,
        mailbox_db_path: Path,
    ) -> None:
        with closing(MailboxInboxPersistence(mailbox_db_path)) as persistence:
            mailbox = IngestionMailbox(
                pipeline=MagicMock(spec=IntakePipeline),
                persistence=persistence,
            )
            mailbox.post(
                {"event_type": "first", "payload": {"n": 1}},
                sender="s",
                tenant_id=_TENANT,
            )
            mailbox.post(
                {"event_type": "second", "payload": {"n": 2}},
                sender="s",
                tenant_id=_TENANT,
            )
            mailbox.post(
                {"event_type": "other", "payload": {"n": 3}},
                sender="s",
                tenant_id="t-other",
            )

        with closing(MailboxInboxPersistence(mailbox_db_path)) as rehydrated_persistence:
            rehydrated_mailbox = IngestionMailbox(
                pipeline=MagicMock(spec=IntakePipeline),
                persistence=rehydrated_persistence,
            )

            drained = rehydrated_mailbox.drain(_TENANT)
            assert [event["event_type"] for event in drained] == ["first", "second"]
            assert rehydrated_mailbox.drain(_TENANT) == []
            assert rehydrated_mailbox.heartbeat()["inbox_depth"] == 1
            assert [event["event_type"] for event in rehydrated_mailbox.drain("t-other")] == [
                "other"
            ]


# ---------------------------------------------------------------------------
# MB-04 / MB-05: heartbeat() shape and depth
# ---------------------------------------------------------------------------


class TestMailboxHeartbeat:
    """MB-04/MB-05: heartbeat() returns correct shape and depth."""

    def test_heartbeat_shape(self) -> None:
        mailbox = IngestionMailbox(pipeline=MagicMock(spec=IntakePipeline))
        hb = mailbox.heartbeat()
        assert hb["status"] == "ok"
        assert hb["pipeline_healthy"] is True
        assert isinstance(hb["inbox_depth"], int)

    def test_heartbeat_depth_reflects_queued_events(self) -> None:
        mailbox = IngestionMailbox(pipeline=MagicMock(spec=IntakePipeline))
        mailbox.post({"event_type": "x", "payload": {}}, sender="s", tenant_id="t1")
        mailbox.post({"event_type": "y", "payload": {}}, sender="s", tenant_id="t2")
        assert mailbox.heartbeat()["inbox_depth"] == 2

    def test_heartbeat_invalid_event_raises(self) -> None:
        mailbox = IngestionMailbox(pipeline=MagicMock(spec=IntakePipeline))
        with pytest.raises(ValueError, match="event_type"):
            mailbox.post({"event_type": "", "payload": {}}, sender="s", tenant_id="t")
        with pytest.raises(ValueError, match="payload"):
            mailbox.post({"event_type": "ok", "payload": "not-a-dict"}, sender="s", tenant_id="t")  # type: ignore[arg-type]

    def test_heartbeat_depth_reads_from_persisted_inbox(self, mailbox_db_path: Path) -> None:
        with closing(MailboxInboxPersistence(mailbox_db_path)) as persistence:
            mailbox = IngestionMailbox(
                pipeline=MagicMock(spec=IntakePipeline),
                persistence=persistence,
            )
            mailbox.post({"event_type": "x", "payload": {}}, sender="s", tenant_id="t1")
            mailbox.post({"event_type": "y", "payload": {}}, sender="s", tenant_id="t2")

        with closing(MailboxInboxPersistence(mailbox_db_path)) as rehydrated_persistence:
            rehydrated_mailbox = IngestionMailbox(
                pipeline=MagicMock(spec=IntakePipeline),
                persistence=rehydrated_persistence,
            )

            assert rehydrated_mailbox.heartbeat()["inbox_depth"] == 2

    def test_candidate_asset_does_not_accumulate_in_persisted_inbox(
        self,
        mailbox_db_path: Path,
    ) -> None:
        mock_pipeline = MagicMock(spec=IntakePipeline)
        with closing(MailboxInboxPersistence(mailbox_db_path)) as persistence:
            mailbox = IngestionMailbox(pipeline=mock_pipeline, persistence=persistence)

            mailbox.post(
                {
                    "event_type": "candidate_asset",
                    "payload": {
                        "name": "persisted-route-skill",
                        "source_uri": "https://example.com/skill",
                        "confidence": "high",
                        "asset_type": "skill",
                    },
                },
                sender="operator-1",
                tenant_id=_TENANT,
            )

        with closing(MailboxInboxPersistence(mailbox_db_path)) as rehydrated_persistence:
            rehydrated_mailbox = IngestionMailbox(
                pipeline=MagicMock(spec=IntakePipeline),
                persistence=rehydrated_persistence,
            )

            mock_pipeline.submit.assert_called_once()
            assert rehydrated_mailbox.heartbeat()["inbox_depth"] == 0
            assert rehydrated_mailbox.drain(_TENANT) == []


# ---------------------------------------------------------------------------
# TM-01 / TM-02 / TM-03 / TM-04 / TM-05: TaskMetricsCollector
# ---------------------------------------------------------------------------


class TestTaskMetricsCollector:
    """TM-01..TM-05: record(), summary(), reset() correctness."""

    def test_record_and_summary_totals(self) -> None:
        mc = TaskMetricsCollector()
        mc.record("evt", _TENANT, success=True, latency_ms=10.0)
        mc.record("evt", _TENANT, success=False, latency_ms=20.0)
        mc.record("evt", _TENANT, success=True, latency_ms=30.0)

        s = mc.summary()
        assert s["total"] == 3
        assert s["success_count"] == 2
        assert s["failure_count"] == 1
        assert s["avg_latency_ms"] == pytest.approx(20.0)

    def test_summary_filtered_by_tenant_id(self) -> None:
        mc = TaskMetricsCollector()
        mc.record("evt", "t-a", success=True, latency_ms=5.0)
        mc.record("evt", "t-b", success=False, latency_ms=15.0)

        sa = mc.summary("t-a")
        sb = mc.summary("t-b")

        assert sa["total"] == 1
        assert sa["success_count"] == 1
        assert sb["total"] == 1
        assert sb["failure_count"] == 1

    def test_reset_tenant_specific(self) -> None:
        mc = TaskMetricsCollector()
        mc.record("e", "t-a", success=True)
        mc.record("e", "t-b", success=True)

        mc.reset("t-a")

        assert mc.summary("t-a")["total"] == 0
        assert mc.summary("t-b")["total"] == 1

    def test_reset_all(self) -> None:
        mc = TaskMetricsCollector()
        mc.record("e", "t-a", success=True)
        mc.record("e", "t-b", success=True)

        mc.reset()

        assert mc.summary()["total"] == 0

    def test_avg_latency_none_when_no_latencies(self) -> None:
        mc = TaskMetricsCollector()
        mc.record("e", "t", success=True)
        assert mc.summary()["avg_latency_ms"] is None

    def test_metadata_stored_in_record(self) -> None:
        mc = TaskMetricsCollector()
        mc.record("e", "t", success=True, metadata={"key": "val"})
        # Access internal records to verify metadata stored correctly
        assert mc._records[0]["metadata"] == {"key": "val"}

    def test_recorded_at_is_iso8601(self) -> None:
        from datetime import datetime

        mc = TaskMetricsCollector()
        mc.record("e", "t", success=True)
        ts = mc._records[0]["recorded_at"]
        # Should parse without error
        datetime.fromisoformat(ts)

    def test_persisted_records_survive_reinstantiation(self, tmp_path: Path) -> None:
        db_path = tmp_path / "task-metrics.db"
        with closing(TaskMetricsCollector(db_path)) as collector:
            collector.record("persisted", _TENANT, success=True, latency_ms=12.5)

        with closing(TaskMetricsCollector(db_path)) as rehydrated:
            summary = rehydrated.summary(_TENANT)
            assert summary["total"] == 1
            history = rehydrated.history(_TENANT)
            assert len(history) == 1
            assert history[0]["event_type"] == "persisted"

    def test_cleanup_expired_removes_old_persisted_metrics(self, tmp_path: Path) -> None:
        import sqlite3
        from datetime import UTC, datetime, timedelta

        db_path = tmp_path / "task-metrics.db"
        with closing(TaskMetricsCollector(db_path, retention_days=30)) as collector:
            collector.record("expired-event", _TENANT, success=False)
            collector.record("recent-event", _TENANT, success=True)

        expired_ts = (datetime.now(UTC) - timedelta(days=45)).isoformat()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE ingestion_task_metrics SET recorded_at = ? WHERE event_type = ?",
                (expired_ts, "expired-event"),
            )
            conn.commit()

        with closing(TaskMetricsCollector(db_path, retention_days=30)) as collector:
            deleted = collector.cleanup_expired()
            assert deleted == 1
            history = collector.history(_TENANT)
            assert [record["event_type"] for record in history] == ["recent-event"]


# ---------------------------------------------------------------------------
# API-01: POST /v1/ingestion/mailbox returns {"status": "accepted", "event_id": ...}
# ---------------------------------------------------------------------------


class TestMailboxPostEndpoint:
    """API-01/API-02/API-06/API-07: POST /v1/ingestion/mailbox behaviour."""

    def test_post_returns_accepted_and_event_id(self) -> None:
        client = _client(["ingestion:write"])
        resp = client.post(
            "/v1/ingestion/mailbox",
            json={"event_type": "custom_event", "payload": {"k": "v"}, "sender": "op"},
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert "event_id" in data
        assert isinstance(data["event_id"], str)

    def test_post_candidate_asset_returns_accepted(self) -> None:
        """API-02: candidate_asset event is accepted without error."""
        client = _client(["ingestion:write"])
        resp = client.post(
            "/v1/ingestion/mailbox",
            json={
                "event_type": "candidate_asset",
                "payload": {
                    "name": "api-skill",
                    "source_uri": "https://example.com",
                    "confidence": "low",
                    "asset_type": "skill",
                    "tenant_id": _TENANT,
                },
                "sender": "pipeline-op",
            },
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "accepted"

    def test_post_increments_metrics(self) -> None:
        """API-06: A successful post records a metric."""
        metrics = ingestion_mod._task_metrics
        client = _client(["ingestion:write"])
        client.post(
            "/v1/ingestion/mailbox",
            json={"event_type": "ping", "payload": {}, "sender": "op"},
        )
        assert metrics.summary()["total"] >= 1

    def test_post_requires_write_scope(self) -> None:
        """API-07: Missing ingestion:write scope yields 401/403."""
        client = _client(["ingestion:read"])
        resp = client.post(
            "/v1/ingestion/mailbox",
            json={"event_type": "ping", "payload": {}, "sender": "op"},
        )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# API-03 / API-08: GET /v1/ingestion/mailbox/drain
# ---------------------------------------------------------------------------


class TestMailboxDrainEndpoint:
    """API-03/API-08: GET /v1/ingestion/mailbox/drain."""

    def test_drain_returns_list(self) -> None:
        """API-03: drain returns a list (may be empty on a fresh install)."""
        client = _client(["ingestion:read"])
        resp = client.get("/v1/ingestion/mailbox/drain")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_drain_returns_previously_posted_event(self) -> None:
        writer = _client(["ingestion:write"])
        reader = _client(["ingestion:read"])

        writer.post(
            "/v1/ingestion/mailbox",
            json={"event_type": "metrics_event", "payload": {"x": 1}, "sender": "bot"},
        )
        resp = reader.get("/v1/ingestion/mailbox/drain")
        assert resp.status_code == 200
        events = resp.json()
        # The event was posted by a user with _TENANT; drain uses _TENANT too
        assert any(e["event_type"] == "metrics_event" for e in events)

    def test_heartbeat_and_drain_use_persisted_mailbox_backend(
        self,
        mailbox_db_path: Path,
    ) -> None:
        persistence = MailboxInboxPersistence(mailbox_db_path)
        persisted_mailbox = IngestionMailbox(
            pipeline=MagicMock(spec=IntakePipeline),
            persistence=persistence,
        )
        previous_mailbox = ingestion_mod._ingestion_mailbox
        ingestion_mod._ingestion_mailbox = persisted_mailbox
        try:
            writer = _client(["ingestion:write"])
            reader = _client(["ingestion:read"])

            post_resp = writer.post(
                "/v1/ingestion/mailbox",
                json={"event_type": "persisted_event", "payload": {"x": 1}, "sender": "bot"},
            )
            assert post_resp.status_code == 202

            heartbeat_resp = _anon_client().get("/v1/ingestion/heartbeat")
            assert heartbeat_resp.status_code == 200
            assert heartbeat_resp.json()["inbox_depth"] == 1

            drain_resp = reader.get("/v1/ingestion/mailbox/drain")
            assert drain_resp.status_code == 200
            assert [event["event_type"] for event in drain_resp.json()] == ["persisted_event"]

            heartbeat_after_drain = _anon_client().get("/v1/ingestion/heartbeat")
            assert heartbeat_after_drain.status_code == 200
            assert heartbeat_after_drain.json()["inbox_depth"] == 0
        finally:
            ingestion_mod._ingestion_mailbox = previous_mailbox
            persistence.close()

    def test_drain_requires_read_scope(self) -> None:
        """API-08: Missing ingestion:read scope yields 401/403."""
        client = _client([])
        resp = client.get("/v1/ingestion/mailbox/drain")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# API-04: GET /v1/ingestion/heartbeat — unauthenticated
# ---------------------------------------------------------------------------


class TestHeartbeatEndpoint:
    """API-04: Heartbeat is public and returns the correct shape."""

    def test_heartbeat_is_unauthenticated(self) -> None:
        resp = _anon_client().get("/v1/ingestion/heartbeat")
        assert resp.status_code == 200

    def test_heartbeat_response_shape(self) -> None:
        resp = _anon_client().get("/v1/ingestion/heartbeat")
        data = resp.json()
        assert data["status"] == "ok"
        assert data["pipeline_healthy"] is True
        assert isinstance(data["inbox_depth"], int)
        assert "pipeline_stats" in data
        assert isinstance(data["pipeline_stats"], dict)

    def test_heartbeat_pipeline_stats_has_expected_keys(self) -> None:
        resp = _anon_client().get("/v1/ingestion/heartbeat")
        stats = resp.json()["pipeline_stats"]
        # Each CandidateStatus value should appear in stats
        for key in ("candidate", "validated", "published", "revoked"):
            assert key in stats


# ---------------------------------------------------------------------------
# API-05: GET /v1/ingestion/metrics
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    """API-05/API-09/API-10: ingestion task metrics endpoints."""

    def test_metrics_returns_summary_shape(self) -> None:
        client = _client(["ingestion:read"])
        resp = client.get("/v1/ingestion/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "success_count" in data
        assert "failure_count" in data
        assert "avg_latency_ms" in data

    def test_metrics_requires_read_scope(self) -> None:
        """API-09: Missing ingestion:read scope yields 401/403."""
        client = _client([])
        resp = client.get("/v1/ingestion/metrics")
        assert resp.status_code in (401, 403)

    def test_metrics_reflects_mailbox_posts(self) -> None:
        """After posting events through the mailbox, metrics total increases."""
        writer = _client(["ingestion:write"])
        reader = _client(["ingestion:read"])

        writer.post(
            "/v1/ingestion/mailbox",
            json={"event_type": "tracked_event", "payload": {}, "sender": "op"},
        )

        resp = reader.get("/v1/ingestion/metrics")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    def test_metrics_history_returns_recent_records(self) -> None:
        writer = _client(["ingestion:write"])
        reader = _client(["ingestion:read"])

        writer.post(
            "/v1/ingestion/mailbox",
            json={"event_type": "first-event", "payload": {}, "sender": "op"},
        )
        writer.post(
            "/v1/ingestion/mailbox",
            json={"event_type": "second-event", "payload": {}, "sender": "op"},
        )

        resp = reader.get("/v1/ingestion/metrics/history?limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "second-event"
