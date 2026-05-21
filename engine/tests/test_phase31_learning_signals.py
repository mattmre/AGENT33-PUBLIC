"""Phase 31 — Continuous learning signals tests."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agent33.config import settings
from agent33.improvement.models import (
    LearningSignal,
    LearningSignalSeverity,
    LearningSignalType,
    LearningTrendDimension,
    LearningTrendDirection,
)
from agent33.improvement.persistence import (
    FileLearningSignalStore,
    InMemoryLearningSignalStore,
    SQLiteLearningSignalStore,
    backup_learning_state,
    migrate_file_learning_state_to_db,
    restore_learning_state,
)
from agent33.improvement.service import ImprovementService, LearningPersistencePolicy
from agent33.main import app
from agent33.security.auth import create_access_token

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture()
def service() -> ImprovementService:
    return ImprovementService()


@pytest.fixture(autouse=True)
def _reset_learning_route_state(monkeypatch: pytest.MonkeyPatch):
    from agent33.api.routes.improvements import _reset_service

    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "memory")
    monkeypatch.setattr(settings, "improvement_learning_persistence_path", "unused.json")
    monkeypatch.setattr(settings, "improvement_learning_persistence_db_path", "unused.sqlite3")
    monkeypatch.setattr(settings, "improvement_learning_persistence_migrate_on_start", False)
    monkeypatch.setattr(
        settings,
        "improvement_learning_persistence_migration_backup_on_start",
        False,
    )
    monkeypatch.setattr(
        settings,
        "improvement_learning_persistence_migration_backup_path",
        "var/improvement_learning_signals.backup.json",
    )
    monkeypatch.setattr(settings, "improvement_learning_file_corruption_behavior", "reset")
    monkeypatch.setattr(settings, "improvement_learning_db_corruption_behavior", "reset")
    monkeypatch.setattr(settings, "improvement_learning_dedupe_window_minutes", 0)
    monkeypatch.setattr(settings, "improvement_learning_retention_days", 180)
    monkeypatch.setattr(settings, "improvement_learning_max_signals", 5000)
    monkeypatch.setattr(settings, "improvement_learning_max_generated_intakes", 1000)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_min_quality", 0.0)
    _reset_service()
    monkeypatch.setattr(settings, "improvement_learning_enabled", False)
    monkeypatch.setattr(settings, "improvement_learning_summary_default_limit", 50)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_enabled", False)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_min_severity", "high")
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_max_items", 3)
    yield
    _reset_service()


def _tenant_client(tenant_id: str, scopes: list[str] | None = None) -> TestClient:
    token = create_access_token(
        "learning-user",
        scopes=scopes or [],
        tenant_id=tenant_id,
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_settings_reject_invalid_learning_corruption_behavior() -> None:
    from agent33.config import Settings

    with pytest.raises(ValidationError, match="corruption behavior must be one of"):
        Settings(improvement_learning_file_corruption_behavior="invalid")
    with pytest.raises(ValidationError, match="corruption behavior must be one of"):
        Settings(improvement_learning_db_corruption_behavior="invalid")


def test_settings_reject_invalid_learning_quality_threshold() -> None:
    from agent33.config import Settings

    with pytest.raises(
        ValidationError,
        match="improvement_learning_auto_intake_min_quality must be between 0.0 and 1.0",
    ):
        Settings(improvement_learning_auto_intake_min_quality=1.1)


def test_settings_reject_invalid_learning_auto_intake_min_severity() -> None:
    from agent33.config import Settings

    with pytest.raises(
        ValidationError,
        match="improvement_learning_auto_intake_min_severity must be one of",
    ):
        Settings(improvement_learning_auto_intake_min_severity="urgent")


def test_settings_normalize_learning_auto_intake_min_severity() -> None:
    from agent33.config import Settings

    configured = Settings(improvement_learning_auto_intake_min_severity=" HIGH ")
    assert configured.improvement_learning_auto_intake_min_severity == "high"


def test_settings_reject_invalid_learning_auto_intake_max_items() -> None:
    from agent33.config import Settings

    with pytest.raises(
        ValidationError,
        match="improvement_learning_auto_intake_max_items must be at least 1",
    ):
        Settings(improvement_learning_auto_intake_max_items=0)


def test_service_roundtrip_and_summary_counts(service: ImprovementService):
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Build flake in CI",
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.FEEDBACK,
            severity=LearningSignalSeverity.LOW,
            summary="User requests better docs",
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Regression after deploy",
        )
    )

    only_bugs = service.list_learning_signals(signal_type=LearningSignalType.BUG, limit=10)
    assert len(only_bugs) == 2

    summary = service.summarize_learning_signals(limit=10)
    assert summary.total_signals == 3
    assert summary.counts_by_type["bug"] == 2
    assert summary.counts_by_type["feedback"] == 1
    assert summary.counts_by_severity["high"] == 2
    assert summary.counts_by_severity["low"] == 1


def test_learning_signal_quality_enrichment_applied(service: ImprovementService):
    signal = service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="CI failure when integration tests run with production-like fixtures",
            details="Nightly build fails after db migration and retries are exhausted.",
            source="ci",
            context={"pipeline": "nightly", "job": "integration"},
        )
    )
    assert signal.quality_score > 0.7
    assert signal.quality_label == "high"
    assert signal.enrichment["has_source"] == "true"
    assert signal.quality_reasons == ["well_formed_signal"]


def test_file_store_persists_signals_and_generated_intakes(tmp_path: Path):
    store_path = tmp_path / "learning_state.json"
    first = ImprovementService(learning_store=FileLearningSignalStore(str(store_path)))
    first.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.INCIDENT,
            severity=LearningSignalSeverity.CRITICAL,
            summary="Tenant outage",
            tenant_id="tenant-a",
        )
    )
    created = first.generate_intakes_from_learning_signals(max_items=1)
    assert len(created) == 1

    second = ImprovementService(learning_store=FileLearningSignalStore(str(store_path)))
    signals = second.list_learning_signals(tenant_id="tenant-a", limit=10)
    assert len(signals) == 1
    assert signals[0].related_intake_id is not None
    intakes = second.list_intakes(tenant_id="tenant-a")
    assert len(intakes) == 1
    assert intakes[0].generated_from_signal_id == signals[0].signal_id


def test_file_to_db_migration_path(tmp_path: Path):
    file_path = tmp_path / "learning_state.json"
    db_path = tmp_path / "learning_state.sqlite3"

    seed = ImprovementService(learning_store=FileLearningSignalStore(str(file_path)))
    seed.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Persisted in file backend",
            tenant_id="tenant-a",
        )
    )
    seed.generate_intakes_from_learning_signals(max_items=1)

    migrated = migrate_file_learning_state_to_db(str(file_path), str(db_path))
    assert len(migrated.signals) == 1
    assert len(migrated.generated_intakes) == 1

    db_service = ImprovementService(learning_store=SQLiteLearningSignalStore(str(db_path)))
    loaded_signals = db_service.list_learning_signals(tenant_id="tenant-a", limit=10)
    assert len(loaded_signals) == 1
    assert loaded_signals[0].summary == "Persisted in file backend"
    assert len(db_service.list_intakes(tenant_id="tenant-a")) == 1


def test_file_to_db_migration_path_creates_backup_when_requested(tmp_path: Path):
    file_path = tmp_path / "learning_state.json"
    db_path = tmp_path / "learning_state.sqlite3"
    backup_path = tmp_path / "learning_state.backup.json"

    seed = ImprovementService(learning_store=FileLearningSignalStore(str(file_path)))
    seed.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Persisted in file backend",
            tenant_id="tenant-a",
        )
    )

    migrated = migrate_file_learning_state_to_db(
        str(file_path), str(db_path), backup_path=str(backup_path)
    )

    assert len(migrated.signals) == 1
    assert backup_path.exists()
    backup_payload = json.loads(backup_path.read_text(encoding="utf-8"))
    assert len(backup_payload["state"]["signals"]) == 1


def test_backup_and_restore_persisted_learning_state(tmp_path: Path):
    source_path = tmp_path / "source_learning.json"
    backup_path = tmp_path / "backup_learning.json"
    target_path = tmp_path / "target_learning.sqlite3"

    source_store = FileLearningSignalStore(str(source_path))
    source_service = ImprovementService(learning_store=source_store)
    source_service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.INCIDENT,
            severity=LearningSignalSeverity.CRITICAL,
            summary="Needs backup",
            tenant_id="tenant-backup",
        )
    )

    backup_file = backup_learning_state(source_store, str(backup_path))
    assert backup_file.exists()

    target_store = SQLiteLearningSignalStore(str(target_path))
    restored = restore_learning_state(target_store, str(backup_path))
    assert len(restored.signals) == 1

    restored_service = ImprovementService(learning_store=target_store)
    restored_signals = restored_service.list_learning_signals(tenant_id="tenant-backup", limit=10)
    assert len(restored_signals) == 1
    assert restored_signals[0].summary == "Needs backup"


def test_backup_file_uses_versioned_envelope(tmp_path: Path):
    source_path = tmp_path / "source_learning.json"
    backup_path = tmp_path / "backup_learning.json"

    source_store = FileLearningSignalStore(str(source_path))
    source_service = ImprovementService(learning_store=source_store)
    source_service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Versioned backup",
            tenant_id="tenant-envelope",
        )
    )

    backup_learning_state(source_store, str(backup_path))

    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    assert payload["format_version"] == 1
    assert payload["signal_count"] == 1
    assert payload["intake_count"] == 0
    assert payload["signal_intake_map_count"] == 0
    assert payload["checksum_sha256"]
    assert payload["state"]["signals"][0]["summary"] == "Versioned backup"


def test_restore_learning_state_accepts_legacy_raw_backup(tmp_path: Path):
    backup_path = tmp_path / "legacy_backup.json"
    target_store = SQLiteLearningSignalStore(str(tmp_path / "restored.sqlite3"))

    backup_path.write_text(
        json.dumps(
            {
                "signals": [
                    {
                        "signal_id": "SIG-legacy",
                        "signal_type": "bug",
                        "severity": "high",
                        "summary": "Legacy backup payload",
                        "tenant_id": "tenant-legacy",
                    }
                ],
                "generated_intakes": [],
                "signal_intake_map": {},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    restored = restore_learning_state(target_store, str(backup_path))

    assert len(restored.signals) == 1
    assert restored.signals[0].summary == "Legacy backup payload"


def test_restore_learning_state_rejects_checksum_mismatch(tmp_path: Path):
    source_store = InMemoryLearningSignalStore()
    source_service = ImprovementService(learning_store=source_store)
    source_service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Checksum mismatch",
            tenant_id="tenant-checksum",
        )
    )
    backup_path = tmp_path / "checksum_backup.json"
    backup_learning_state(source_store, str(backup_path))
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    payload["state"]["signals"][0]["summary"] = "Tampered backup"
    backup_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="Backup checksum validation failed"):
        restore_learning_state(
            SQLiteLearningSignalStore(str(tmp_path / "target.sqlite3")),
            str(backup_path),
        )


def test_restore_learning_state_rejects_count_mismatch(tmp_path: Path):
    source_store = InMemoryLearningSignalStore()
    source_service = ImprovementService(learning_store=source_store)
    source_service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Count mismatch",
            tenant_id="tenant-count",
        )
    )
    backup_path = tmp_path / "count_backup.json"
    backup_learning_state(source_store, str(backup_path))
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    payload["signal_count"] = 2
    backup_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="Backup metadata signal_count does not match payload"):
        restore_learning_state(
            SQLiteLearningSignalStore(str(tmp_path / "target.sqlite3")),
            str(backup_path),
        )


def test_restore_learning_state_rejects_unsupported_backup_format_version(tmp_path: Path):
    source_store = InMemoryLearningSignalStore()
    source_service = ImprovementService(learning_store=source_store)
    source_service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Unsupported version",
            tenant_id="tenant-version",
        )
    )
    backup_path = tmp_path / "unsupported_version_backup.json"
    backup_learning_state(source_store, str(backup_path))
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    payload["format_version"] = 99
    backup_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported backup format version: 99"):
        restore_learning_state(
            SQLiteLearningSignalStore(str(tmp_path / "target.sqlite3")),
            str(backup_path),
        )


def test_restore_learning_state_requires_format_version_in_envelope(tmp_path: Path):
    source_store = InMemoryLearningSignalStore()
    source_service = ImprovementService(learning_store=source_store)
    source_service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Missing version",
            tenant_id="tenant-version",
        )
    )
    backup_path = tmp_path / "missing_version_backup.json"
    backup_learning_state(source_store, str(backup_path))
    payload = json.loads(backup_path.read_text(encoding="utf-8"))
    del payload["format_version"]
    backup_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid backup envelope"):
        restore_learning_state(
            SQLiteLearningSignalStore(str(tmp_path / "target.sqlite3")),
            str(backup_path),
        )


def test_file_store_corruption_recovery_is_deterministic(tmp_path: Path):
    corrupt_path = tmp_path / "corrupt_learning.json"
    corrupt_path.write_text("{not-json", encoding="utf-8")

    store = FileLearningSignalStore(str(corrupt_path), on_corruption="reset")
    state = store.load()

    assert state.signals == []
    assert not corrupt_path.exists()
    assert (tmp_path / "corrupt_learning.json.corrupt").exists()


def test_sqlite_store_corruption_reset_writes_sidecar_and_clears_row(tmp_path: Path):
    db_path = tmp_path / "corrupt_learning.sqlite3"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_signal_state (
                state_key INTEGER PRIMARY KEY CHECK (state_key = 1),
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO learning_signal_state(state_key, payload) VALUES (1, ?)",
            ("{not-json",),
        )
        conn.commit()

    store = SQLiteLearningSignalStore(str(db_path), on_corruption="reset")
    loaded = store.load()

    assert loaded.signals == []
    sidecars = sorted(tmp_path.glob("corrupt_learning.sqlite3.corrupt.payload*.json"))
    assert len(sidecars) == 1
    assert sidecars[0].read_text(encoding="utf-8") == "{not-json"
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload FROM learning_signal_state WHERE state_key = 1"
        ).fetchone()
    assert row is None


def test_sqlite_store_corruption_raise_throws_value_error(tmp_path: Path):
    db_path = tmp_path / "corrupt_learning.sqlite3"

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_signal_state (
                state_key INTEGER PRIMARY KEY CHECK (state_key = 1),
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO learning_signal_state(state_key, payload) VALUES (1, ?)",
            ("{not-json",),
        )
        conn.commit()

    store = SQLiteLearningSignalStore(str(db_path), on_corruption="raise")
    with pytest.raises(
        ValueError,
        match=(
            f"^Corrupted learning-signal persistence payload in SQLite: {re.escape(str(db_path))}$"
        ),
    ):
        store.load()


def test_sqlite_database_corruption_reset_quarantines_db_file(tmp_path: Path):
    db_path = tmp_path / "corrupt_db.sqlite3"
    db_path.write_bytes(b"not-a-sqlite-database")

    store = SQLiteLearningSignalStore(str(db_path), on_corruption="reset")
    loaded = store.load()

    assert loaded.signals == []
    assert not db_path.exists()
    sidecars = sorted(tmp_path.glob("corrupt_db.sqlite3.corrupt*"))
    assert len(sidecars) == 1


def test_sqlite_database_corruption_raise_throws_value_error(tmp_path: Path):
    db_path = tmp_path / "corrupt_db.sqlite3"
    db_path.write_bytes(b"not-a-sqlite-database")

    store = SQLiteLearningSignalStore(str(db_path), on_corruption="raise")
    with pytest.raises(
        ValueError,
        match=(f"^Corrupted learning-signal SQLite database: {re.escape(str(db_path))}$"),
    ):
        store.load()


def test_summary_supports_tenant_and_window_trends(service: ImprovementService):
    now = datetime.now(UTC)
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            tenant_id="tenant-a",
            summary="fresh-a",
            recorded_at=now - timedelta(days=1),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.FEEDBACK,
            severity=LearningSignalSeverity.MEDIUM,
            tenant_id="tenant-a",
            summary="older-a",
            recorded_at=now - timedelta(days=8),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            tenant_id="tenant-b",
            summary="fresh-b",
            recorded_at=now - timedelta(days=1),
        )
    )

    summary = service.summarize_learning_signals(limit=10, tenant_id="tenant-a", window_days=7)
    assert summary.total_signals == 1
    assert summary.counts_by_tenant == {"tenant-a": 1}
    assert summary.previous_window_total == 1
    assert summary.trend_delta == 0
    assert summary.trend_direction == "stable"


def test_trend_report_is_dedupe_aware_by_signal_type() -> None:
    service = ImprovementService(
        persistence_policy=LearningPersistencePolicy(dedupe_window_minutes=60 * 24 * 30)
    )
    now = datetime.now(UTC)
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            tenant_id="tenant-a",
            summary="legacy flaky test",
            source="ci",
            recorded_at=now - timedelta(days=9),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            tenant_id="tenant-a",
            summary="release pipeline regression",
            source="ci",
            recorded_at=now - timedelta(days=2),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.CRITICAL,
            tenant_id="tenant-a",
            summary="release pipeline regression",
            source="ci",
            recorded_at=now - timedelta(days=1),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.INCIDENT,
            severity=LearningSignalSeverity.CRITICAL,
            tenant_id="tenant-a",
            summary="incident after deploy",
            source="pagerduty",
            recorded_at=now - timedelta(days=1),
        )
    )

    report = service.trend_learning_signals(
        window_days=7,
        dimension=LearningTrendDimension.SIGNAL_TYPE,
        tenant_id="tenant-a",
    )

    assert report.total_current_signals == 2
    assert report.total_previous_signals == 1
    assert report.total_current_occurrences == 3
    assert report.total_previous_occurrences == 1
    bug = next(item for item in report.categories if item.key == "bug")
    assert bug.current_signals == 1
    assert bug.previous_signals == 1
    assert bug.current_occurrences == 2
    assert bug.previous_occurrences == 1
    assert bug.occurrence_delta == 1
    assert bug.direction == LearningTrendDirection.UP


def test_auto_intake_priority_uses_quality_score(service: ImprovementService):
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Short",
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Detailed recurring bug in release pipeline after dependency bump",
            details="Observed in two regions with canary and stable lanes.",
            source="ci",
            context={"region": "us-east", "release": "2026.02"},
        )
    )
    created = service.generate_intakes_from_learning_signals(
        min_severity=LearningSignalSeverity.HIGH,
        max_items=2,
    )
    assert len(created) == 2
    scores = [intake.relevance.priority_score for intake in created]
    assert scores[0] >= scores[1]
    assert created[0].automated_quality_score is not None


def test_auto_intake_respects_min_quality_threshold() -> None:
    service = ImprovementService(
        persistence_policy=LearningPersistencePolicy(auto_intake_min_quality=0.6)
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Short",
        )
    )
    high_quality_signal = service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Detailed recurring bug in release pipeline after dependency bump",
            details="Observed in two regions with canary and stable lanes.",
            source="ci",
            context={"region": "us-east", "release": "2026.02"},
        )
    )

    created = service.generate_intakes_from_learning_signals(
        min_severity=LearningSignalSeverity.HIGH,
        max_items=5,
    )
    assert len(created) == 1
    assert created[0].generated_from_signal_id == high_quality_signal.signal_id


def test_calibration_report_recommends_thresholds_from_windowed_sample() -> None:
    service = ImprovementService(
        persistence_policy=LearningPersistencePolicy(
            max_signals=120,
            auto_intake_min_quality=0.45,
        )
    )
    now = datetime.now(UTC)
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.FEEDBACK,
            severity=LearningSignalSeverity.MEDIUM,
            tenant_id="tenant-a",
            summary="short",
            recorded_at=now - timedelta(days=1),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            tenant_id="tenant-a",
            summary="Detailed recurring bug in release pipeline after dependency bump",
            details="Observed in two regions with canary and stable lanes.",
            source="ci",
            context={"region": "us-east", "release": "2026.02"},
            recorded_at=now - timedelta(days=2),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.INCIDENT,
            severity=LearningSignalSeverity.CRITICAL,
            tenant_id="tenant-a",
            summary="Critical production outage with cascading dependency failures",
            details=(
                "API layer timed out, queue depth spiked, and worker retries exhausted "
                "across multiple availability zones."
            ),
            source="pagerduty",
            context={"region": "us-east", "service": "gateway", "cluster": "prod-1"},
            recorded_at=now - timedelta(days=3),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            tenant_id="tenant-a",
            summary="outside window signal",
            recorded_at=now - timedelta(days=45),
        )
    )

    report = service.calibrate_learning_thresholds(
        window_days=14,
        target_auto_intakes_per_window=2,
        tenant_id="tenant-a",
    )
    assert report.sample_signals == 3
    assert report.sample_occurrences >= report.sample_signals
    assert 0.0 <= report.observed_average_quality_score <= 1.0
    assert report.recommended_auto_intake_max_items == 2
    assert report.recommended_auto_intake_min_severity in {"medium", "high"}
    assert 0.0 <= report.recommended_auto_intake_min_quality <= 1.0
    assert 30 <= report.recommended_retention_days <= 365
    assert report.policy_snapshot["auto_intake_min_quality"] == 0.45
    assert report.rationale


def test_calibrate_zero_signals_returns_conservative_defaults() -> None:
    """When no signals exist in the window, conservative defaults are returned."""
    policy = LearningPersistencePolicy(
        auto_intake_min_quality=0.6,
        auto_intake_min_severity=LearningSignalSeverity.MEDIUM,
        auto_intake_max_items=5,
    )
    service = ImprovementService(persistence_policy=policy)

    report = service.calibrate_learning_thresholds(
        window_days=7,
        target_auto_intakes_per_window=5,
    )
    assert report.sample_signals == 0
    assert report.sample_occurrences == 0
    assert report.observed_average_quality_score == 0.0
    assert report.observed_quality_p75 == 0.0
    assert report.observed_quality_p90 == 0.0
    assert report.observed_high_or_critical_ratio == 0.0
    # Conservative defaults: use current policy quality, cap items to 1, high severity
    assert report.recommended_auto_intake_min_quality == 0.6
    assert report.recommended_auto_intake_max_items == 1
    assert report.recommended_auto_intake_min_severity == "high"
    assert report.rationale == [
        "No signals in the selected window; returning conservative defaults.",
    ]
    # Policy snapshot uses None for unconfigured values
    assert report.policy_snapshot["auto_intake_min_quality"] == 0.6
    assert report.policy_snapshot["auto_intake_min_severity"] == "medium"
    assert report.policy_snapshot["auto_intake_max_items"] == 5
    assert report.policy_snapshot["max_signals"] is None
    assert report.policy_snapshot["retention_days"] is None


def test_dedupe_window_merges_duplicate_learning_signals() -> None:
    service = ImprovementService(
        persistence_policy=LearningPersistencePolicy(dedupe_window_minutes=60)
    )
    now = datetime.now(UTC)
    first = service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Release pipeline regression",
            source="ci",
            tenant_id="tenant-a",
            details="first observation",
            context={"job": "smoke"},
            recorded_at=now - timedelta(minutes=10),
        )
    )
    second = service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.CRITICAL,
            summary="  release  pipeline regression  ",
            source="CI",
            tenant_id="tenant-a",
            details="second observation has richer details",
            context={"region": "us-east"},
            recorded_at=now,
        )
    )

    assert first.signal_id == second.signal_id
    assert second.occurrence_count == 2
    assert second.severity == LearningSignalSeverity.CRITICAL
    assert second.last_seen_at == now
    assert second.context["job"] == "smoke"
    assert second.context["region"] == "us-east"
    assert len(service.list_learning_signals(limit=10)) == 1


def test_persistence_policy_prunes_signal_and_intake_history() -> None:
    service = ImprovementService(
        persistence_policy=LearningPersistencePolicy(
            max_signals=1,
            max_generated_intakes=1,
        )
    )
    old_signal = service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="older signal",
            source="ci",
            recorded_at=datetime.now(UTC) - timedelta(days=2),
        )
    )
    service.generate_intakes_from_learning_signals(max_items=1)

    new_signal = service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.INCIDENT,
            severity=LearningSignalSeverity.CRITICAL,
            summary="newer signal",
            source="pagerduty",
            recorded_at=datetime.now(UTC),
        )
    )
    service.generate_intakes_from_learning_signals(max_items=1)

    signals = service.list_learning_signals(limit=10)
    assert len(signals) == 1
    assert signals[0].signal_id == new_signal.signal_id
    assert signals[0].signal_id != old_signal.signal_id

    generated_intakes = [
        intake for intake in service.list_intakes() if intake.generated_from_signal_id is not None
    ]
    assert len(generated_intakes) == 1
    assert generated_intakes[0].generated_from_signal_id == new_signal.signal_id


def test_retention_days_prunes_expired_signals() -> None:
    service = ImprovementService(
        persistence_policy=LearningPersistencePolicy(
            retention_days=7,
            max_signals=10,
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="expired signal",
            recorded_at=datetime.now(UTC) - timedelta(days=21),
        )
    )
    fresh = service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="fresh signal",
            recorded_at=datetime.now(UTC) - timedelta(days=1),
        )
    )

    signals = service.list_learning_signals(limit=10)
    assert len(signals) == 1
    assert signals[0].signal_id == fresh.signal_id


def test_idempotent_intake_generation(service: ImprovementService):
    signal = service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.INCIDENT,
            severity=LearningSignalSeverity.HIGH,
            summary="Production timeout spike",
        )
    )

    first = service.generate_intakes_from_learning_signals(
        min_severity=LearningSignalSeverity.HIGH, max_items=3
    )
    second = service.generate_intakes_from_learning_signals(
        min_severity=LearningSignalSeverity.HIGH, max_items=3
    )

    assert len(first) == 1
    assert len(second) == 0
    assert signal.intake_generated is True
    assert signal.related_intake_id == first[0].intake_id


def test_routes_404_when_feature_disabled(client: TestClient):
    assert (
        client.post(
            "/v1/improvements/learning/signals",
            json={"signal_type": "bug", "severity": "high", "summary": "x"},
        ).status_code
        == 404
    )
    assert client.get("/v1/improvements/learning/signals").status_code == 404
    assert client.get("/v1/improvements/learning/summary").status_code == 404


def test_routes_record_and_list_when_enabled(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)

    created = client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "bug",
            "severity": "high",
            "summary": "New flaky test discovered",
            "details": "Observed in nightly run",
            "source": "ci",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["signal_id"].startswith("LS-")
    assert body["signal_type"] == "bug"
    assert body["severity"] == "high"

    listed = client.get(
        "/v1/improvements/learning/signals",
        params={
            "signal_type": "bug",
            "severity": "high",
            "tenant_id": "default",
            "limit": 10,
        },
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_summary_generate_intakes_respects_auto_intake_flag(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)

    client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "incident",
            "severity": "high",
            "summary": "Retry storm after deploy",
        },
    )

    monkeypatch.setattr(settings, "improvement_learning_auto_intake_enabled", False)
    no_intakes = client.get(
        "/v1/improvements/learning/summary",
        params={"generate_intakes": "true"},
    )
    assert no_intakes.status_code == 200
    assert no_intakes.json()["generated_intakes"] == []

    monkeypatch.setattr(settings, "improvement_learning_auto_intake_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_min_severity", "high")
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_max_items", 3)

    with_intakes = client.get(
        "/v1/improvements/learning/summary",
        params={"generate_intakes": "true"},
    )
    assert with_intakes.status_code == 200
    assert len(with_intakes.json()["generated_intakes"]) == 1

    second = client.get(
        "/v1/improvements/learning/summary",
        params={"generate_intakes": "true"},
    )
    assert second.status_code == 200
    assert second.json()["generated_intakes"] == []


def test_summary_generate_intakes_respects_quality_threshold_setting(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from agent33.api.routes.improvements import _reset_service

    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_min_severity", "high")
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_max_items", 5)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_min_quality", 0.6)
    _reset_service()

    client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "bug",
            "severity": "high",
            "summary": "short",
        },
    )
    low_quality = client.get(
        "/v1/improvements/learning/summary",
        params={"generate_intakes": "true"},
    )
    assert low_quality.status_code == 200
    assert low_quality.json()["generated_intakes"] == []

    client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "bug",
            "severity": "high",
            "summary": "Detailed recurring bug in release pipeline after dependency bump",
            "details": "Observed in two regions with canary and stable lanes.",
            "source": "ci",
            "context": {"region": "us-east", "release": "2026.02"},
        },
    )
    high_quality = client.get(
        "/v1/improvements/learning/summary",
        params={"generate_intakes": "true"},
    )
    assert high_quality.status_code == 200
    assert len(high_quality.json()["generated_intakes"]) == 1


def test_summary_is_tenant_scoped_in_route(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "incident",
            "severity": "high",
            "summary": "tenant one signal",
            "tenant_id": "tenant-1",
        },
    )
    client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "bug",
            "severity": "high",
            "summary": "tenant two signal",
            "tenant_id": "tenant-2",
        },
    )

    response = client.get(
        "/v1/improvements/learning/summary",
        params={"tenant_id": "tenant-1", "window_days": 30},
    )
    assert response.status_code == 200
    payload = response.json()["summary"]
    assert payload["tenant_id"] == "tenant-1"
    assert payload["total_signals"] == 1
    assert payload["counts_by_tenant"] == {"tenant-1": 1}


def test_learning_routes_reject_cross_tenant_override_for_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    tenant_client = _tenant_client("tenant-1")

    create_resp = tenant_client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "incident",
            "severity": "high",
            "summary": "cross-tenant attempt",
            "tenant_id": "tenant-2",
        },
    )
    assert create_resp.status_code == 403
    assert "Tenant mismatch" in create_resp.json()["detail"]

    summary_resp = tenant_client.get(
        "/v1/improvements/learning/summary",
        params={"tenant_id": "tenant-2"},
    )
    assert summary_resp.status_code == 403
    assert "Tenant mismatch" in summary_resp.json()["detail"]


def test_learning_routes_reject_authenticated_user_without_tenant_context(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    tenantless_client = _tenant_client("")

    create_resp = tenantless_client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "incident",
            "severity": "high",
            "summary": "tenantless attempt",
        },
    )
    assert create_resp.status_code == 403
    assert "Tenant context required" in create_resp.json()["detail"]

    summary_resp = tenantless_client.get("/v1/improvements/learning/summary")
    assert summary_resp.status_code == 403
    assert "Tenant context required" in summary_resp.json()["detail"]


def test_trends_route_returns_dimension_report(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    now = datetime.now(UTC)
    from agent33.api.routes.improvements import get_improvement_service

    service = get_improvement_service()
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            tenant_id="tenant-1",
            summary="legacy flaky test",
            source="ci",
            recorded_at=now - timedelta(days=9),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            tenant_id="tenant-1",
            summary="current release pipeline regression",
            source="ci",
            recorded_at=now - timedelta(days=2),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.CRITICAL,
            tenant_id="tenant-1",
            summary="current release pipeline regression",
            source="ci",
            recorded_at=now - timedelta(days=1),
        )
    )

    response = client.get(
        "/v1/improvements/learning/trends",
        params={
            "window_days": 7,
            "dimension": "severity",
            "tenant_id": "tenant-1",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["dimension"] == "severity"
    assert payload["window_days"] == 7
    assert payload["tenant_id"] == "tenant-1"
    assert isinstance(payload["categories"], list)
    assert all(item["direction"] in {"up", "down", "stable"} for item in payload["categories"])


def test_trends_route_rejects_invalid_dimension(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    response = client.get(
        "/v1/improvements/learning/trends",
        params={"dimension": "invalid"},
    )
    assert response.status_code == 400
    assert "Invalid dimension" in response.json()["detail"]


def test_trends_route_rejects_invalid_window_days(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    response = client.get(
        "/v1/improvements/learning/trends",
        params={"window_days": 0},
    )
    assert response.status_code == 400
    assert "window_days must be at least 1" in response.json()["detail"]


def test_calibration_route_returns_report(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_max_items", 2)
    now = datetime.now(UTC)

    from agent33.api.routes.improvements import _reset_service, get_improvement_service

    _reset_service()

    service = get_improvement_service()
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            tenant_id="tenant-1",
            summary="Detailed recurring bug in release pipeline after dependency bump",
            details="Observed in two regions with canary and stable lanes.",
            source="ci",
            context={"region": "us-east", "release": "2026.02"},
            recorded_at=now - timedelta(days=2),
        )
    )
    service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.INCIDENT,
            severity=LearningSignalSeverity.CRITICAL,
            tenant_id="tenant-1",
            summary="Critical outage in production gateway",
            details="Queue saturation and repeated retries observed.",
            source="pagerduty",
            context={"service": "gateway"},
            recorded_at=now - timedelta(days=1),
        )
    )

    response = client.get(
        "/v1/improvements/learning/calibration",
        params={"window_days": 14, "tenant_id": "tenant-1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "tenant-1"
    assert payload["window_days"] == 14
    assert payload["target_auto_intakes_per_window"] == 2
    assert payload["sample_signals"] == 2
    assert payload["recommended_auto_intake_max_items"] == 2
    assert 0.0 <= payload["recommended_auto_intake_min_quality"] <= 1.0


def test_calibration_route_prefers_live_policy_over_stale_settings(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_max_items", 1)

    from agent33.api.routes.improvements import get_improvement_service

    service = get_improvement_service()
    service.update_policy(
        LearningPersistencePolicy(
            dedupe_window_minutes=service._persistence_policy.dedupe_window_minutes,
            retention_days=service._persistence_policy.retention_days,
            max_signals=service._persistence_policy.max_signals,
            max_generated_intakes=service._persistence_policy.max_generated_intakes,
            auto_intake_min_quality=service._persistence_policy.auto_intake_min_quality,
            auto_intake_min_severity=LearningSignalSeverity.MEDIUM,
            auto_intake_max_items=4,
        )
    )

    response = client.get("/v1/improvements/learning/calibration")
    assert response.status_code == 200
    payload = response.json()
    assert payload["target_auto_intakes_per_window"] == 4
    assert payload["policy_snapshot"]["auto_intake_max_items"] == 4
    assert payload["policy_snapshot"]["auto_intake_min_severity"] == "medium"


def test_calibration_route_rejects_invalid_window_days(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    response = client.get(
        "/v1/improvements/learning/calibration",
        params={"window_days": 0},
    )
    assert response.status_code == 400
    assert "window_days must be at least 1" in response.json()["detail"]


def test_calibration_route_rejects_invalid_target_items(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    response = client.get(
        "/v1/improvements/learning/calibration",
        params={"target_auto_intakes_per_window": 0},
    )
    assert response.status_code == 400
    assert "target_auto_intakes_per_window must be at least 1" in response.json()["detail"]


def test_routes_support_sqlite_backend_with_file_migration(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from agent33.api.routes.improvements import _reset_service

    file_path = tmp_path / "learning_state.json"
    db_path = tmp_path / "learning_state.sqlite3"

    file_seed_service = ImprovementService(learning_store=FileLearningSignalStore(str(file_path)))
    file_seed_service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Migrate me",
            tenant_id="tenant-db",
        )
    )

    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "db")
    monkeypatch.setattr(settings, "improvement_learning_persistence_path", str(file_path))
    monkeypatch.setattr(settings, "improvement_learning_persistence_db_path", str(db_path))
    monkeypatch.setattr(settings, "improvement_learning_persistence_migrate_on_start", True)
    _reset_service()

    listed = client.get(
        "/v1/improvements/learning/signals",
        params={"tenant_id": "tenant-db", "limit": 10},
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_routes_sqlite_startup_migration_creates_backup_when_enabled(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from agent33.api.routes.improvements import _reset_service

    file_path = tmp_path / "learning_state.json"
    db_path = tmp_path / "learning_state.sqlite3"
    backup_path = tmp_path / "learning_state.backup.json"

    file_seed_service = ImprovementService(learning_store=FileLearningSignalStore(str(file_path)))
    file_seed_service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Migrate and backup me",
            tenant_id="tenant-db",
        )
    )

    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "db")
    monkeypatch.setattr(settings, "improvement_learning_persistence_path", str(file_path))
    monkeypatch.setattr(settings, "improvement_learning_persistence_db_path", str(db_path))
    monkeypatch.setattr(settings, "improvement_learning_persistence_migrate_on_start", True)
    monkeypatch.setattr(
        settings,
        "improvement_learning_persistence_migration_backup_on_start",
        True,
    )
    monkeypatch.setattr(
        settings,
        "improvement_learning_persistence_migration_backup_path",
        str(backup_path),
    )
    _reset_service()

    listed = client.get(
        "/v1/improvements/learning/signals",
        params={"tenant_id": "tenant-db", "limit": 10},
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert backup_path.exists()


def test_routes_sqlite_startup_migration_does_not_overwrite_existing_db(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from agent33.api.routes.improvements import _reset_service

    file_path = tmp_path / "learning_state.json"
    db_path = tmp_path / "learning_state.sqlite3"

    db_seed_service = ImprovementService(learning_store=SQLiteLearningSignalStore(str(db_path)))
    db_seed_service.record_learning_signal(
        LearningSignal(
            signal_type=LearningSignalType.BUG,
            severity=LearningSignalSeverity.HIGH,
            summary="Keep DB state",
            tenant_id="tenant-db",
        )
    )

    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "db")
    monkeypatch.setattr(settings, "improvement_learning_persistence_path", str(file_path))
    monkeypatch.setattr(settings, "improvement_learning_persistence_db_path", str(db_path))
    monkeypatch.setattr(settings, "improvement_learning_persistence_migrate_on_start", True)
    _reset_service()

    listed = client.get(
        "/v1/improvements/learning/signals",
        params={"tenant_id": "tenant-db", "limit": 10},
    )
    assert listed.status_code == 200
    payload = listed.json()
    assert len(payload) == 1
    assert payload[0]["summary"] == "Keep DB state"


def test_backup_endpoint_creates_portable_backup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from agent33.api.routes.improvements import _reset_service

    file_path = tmp_path / "learning_state.json"
    backup_path = tmp_path / "operator_backup.json"

    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "file")
    monkeypatch.setattr(settings, "improvement_learning_persistence_path", str(file_path))
    _reset_service()

    client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "bug",
            "severity": "high",
            "summary": "Signal for backup test",
        },
    )

    resp = client.post(
        "/v1/improvements/learning/backup",
        json={"backup_path": str(backup_path)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["signal_count"] == 1
    assert body["intake_count"] == 0
    assert backup_path.exists()

    backup_data = json.loads(backup_path.read_text(encoding="utf-8"))
    assert len(backup_data["state"]["signals"]) == 1
    assert backup_data["state"]["signals"][0]["summary"] == "Signal for backup test"


def test_backup_restore_routes_require_admin_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from agent33.api.routes.improvements import _reset_service

    file_path = tmp_path / "learning_state.json"
    backup_path = tmp_path / "operator_backup.json"

    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "file")
    monkeypatch.setattr(settings, "improvement_learning_persistence_path", str(file_path))
    _reset_service()

    tenant_client = _tenant_client("tenant-a")
    backup_resp = tenant_client.post(
        "/v1/improvements/learning/backup",
        json={"backup_path": str(backup_path)},
    )
    assert backup_resp.status_code == 403

    restore_resp = tenant_client.post(
        "/v1/improvements/learning/restore",
        json={"backup_path": str(backup_path)},
    )
    assert restore_resp.status_code == 403


def test_backup_endpoint_uses_default_path_when_omitted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from agent33.api.routes.improvements import _reset_service

    file_path = tmp_path / "learning_state.json"
    default_backup = tmp_path / "default_backup.json"

    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "file")
    monkeypatch.setattr(settings, "improvement_learning_persistence_path", str(file_path))
    monkeypatch.setattr(
        settings,
        "improvement_learning_persistence_migration_backup_path",
        str(default_backup),
    )
    _reset_service()

    resp = client.post("/v1/improvements/learning/backup", json={})
    assert resp.status_code == 200
    assert default_backup.exists()


def test_restore_endpoint_recovers_learning_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from agent33.api.routes.improvements import _reset_service

    file_path = tmp_path / "learning_state.json"
    backup_path = tmp_path / "operator_backup.json"

    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "file")
    monkeypatch.setattr(settings, "improvement_learning_persistence_path", str(file_path))
    _reset_service()

    # Record a signal and back it up
    client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "incident",
            "severity": "critical",
            "summary": "Restore test signal",
            "tenant_id": "tenant-restore",
        },
    )
    client.post(
        "/v1/improvements/learning/backup",
        json={"backup_path": str(backup_path)},
    )

    # Delete persistence file to simulate data loss
    file_path.unlink()
    _reset_service()

    listed = client.get(
        "/v1/improvements/learning/signals",
        params={"tenant_id": "tenant-restore", "limit": 10},
    )
    assert len(listed.json()) == 0

    # Restore from backup
    resp = client.post(
        "/v1/improvements/learning/restore",
        json={"backup_path": str(backup_path)},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["signal_count"] == 1
    assert body["intake_count"] == 0

    # Verify restored data is accessible
    listed = client.get(
        "/v1/improvements/learning/signals",
        params={"tenant_id": "tenant-restore", "limit": 10},
    )
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["summary"] == "Restore test signal"


def test_restore_endpoint_returns_404_for_missing_backup(
    client: TestClient,
):
    resp = client.post(
        "/v1/improvements/learning/restore",
        json={"backup_path": "/nonexistent/backup.json"},
    )
    assert resp.status_code == 404
    assert "Backup file not found" in resp.json()["detail"]


def test_backup_restore_round_trip_preserves_generated_intakes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from agent33.api.routes.improvements import _reset_service

    file_path = tmp_path / "learning_state.json"
    backup_path = tmp_path / "roundtrip_backup.json"

    monkeypatch.setattr(settings, "improvement_learning_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_enabled", True)
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_min_severity", "high")
    monkeypatch.setattr(settings, "improvement_learning_auto_intake_max_items", 5)
    monkeypatch.setattr(settings, "improvement_learning_persistence_backend", "file")
    monkeypatch.setattr(settings, "improvement_learning_persistence_path", str(file_path))
    _reset_service()

    client.post(
        "/v1/improvements/learning/signals",
        json={
            "signal_type": "incident",
            "severity": "high",
            "summary": "Roundtrip signal",
        },
    )
    client.get(
        "/v1/improvements/learning/summary",
        params={"generate_intakes": "true"},
    )

    backup_resp = client.post(
        "/v1/improvements/learning/backup",
        json={"backup_path": str(backup_path)},
    )
    assert backup_resp.status_code == 200
    assert backup_resp.json()["signal_count"] == 1
    assert backup_resp.json()["intake_count"] == 1

    # Simulate data loss
    file_path.unlink()
    _reset_service()

    restore_resp = client.post(
        "/v1/improvements/learning/restore",
        json={"backup_path": str(backup_path)},
    )
    assert restore_resp.status_code == 200
    assert restore_resp.json()["signal_count"] == 1
    assert restore_resp.json()["intake_count"] == 1
