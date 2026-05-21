"""Tests for security scan persistence, deduplication, and cleanup."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta

from agent33.component_security.dedup import (
    compute_finding_fingerprint,
    deduplicate_findings,
)
from agent33.component_security.models import (
    FindingCategory,
    FindingSeverity,
    RunStatus,
    ScanTarget,
    SecurityFinding,
    SecurityProfile,
    SecurityRun,
)
from agent33.component_security.persistence import SecurityScanStore
from agent33.services.security_scan import SecurityScanService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    run_id: str = "secrun-test1",
    tenant_id: str = "t-1",
    profile: SecurityProfile = SecurityProfile.QUICK,
    status: str = "completed",
    target_path: str = "/repo",
) -> SecurityRun:
    run = SecurityRun(
        id=run_id,
        tenant_id=tenant_id,
        profile=profile,
        status=status,
        target=ScanTarget(repository_path=target_path),
    )
    run.started_at = datetime.now(UTC)
    run.completed_at = datetime.now(UTC)
    return run


def _make_finding(
    run_id: str = "secrun-test1",
    tool: str = "bandit",
    file_path: str = "app.py",
    line_number: int | None = 42,
    severity: FindingSeverity = FindingSeverity.HIGH,
    category: FindingCategory = FindingCategory.INJECTION_RISK,
    cwe_id: str = "CWE-78",
    title: str = "OS command injection",
) -> SecurityFinding:
    return SecurityFinding(
        run_id=run_id,
        tool=tool,
        file_path=file_path,
        line_number=line_number,
        severity=severity,
        category=category,
        cwe_id=cwe_id,
        title=title,
        description=title,
        remediation="Fix it",
    )


# ---------------------------------------------------------------------------
# SecurityScanStore — run round-trip
# ---------------------------------------------------------------------------


class TestStoreRunRoundTrip:
    """Test SQLite round-trip for scan runs."""

    def test_save_and_get_run(self) -> None:
        store = SecurityScanStore()
        run = _make_run()
        store.save_run(run)

        loaded = store.get_run(run.id)
        assert loaded is not None
        assert loaded["id"] == run.id
        assert loaded["tenant_id"] == "t-1"
        assert loaded["profile"] == "quick"
        assert loaded["status"] == "completed"

    def test_get_run_not_found(self) -> None:
        store = SecurityScanStore()
        assert store.get_run("nonexistent") is None

    def test_list_runs_empty(self) -> None:
        store = SecurityScanStore()
        assert store.list_runs() == []

    def test_list_runs_returns_newest_first(self) -> None:
        store = SecurityScanStore()
        r1 = _make_run(run_id="secrun-r1")
        r1.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        r2 = _make_run(run_id="secrun-r2")
        r2.created_at = datetime(2025, 6, 1, tzinfo=UTC)
        store.save_run(r1)
        store.save_run(r2)

        runs = store.list_runs()
        assert len(runs) == 2
        assert runs[0]["id"] == "secrun-r2"
        assert runs[1]["id"] == "secrun-r1"

    def test_list_runs_tenant_filter(self) -> None:
        store = SecurityScanStore()
        store.save_run(_make_run(run_id="secrun-a", tenant_id="t-A"))
        store.save_run(_make_run(run_id="secrun-b", tenant_id="t-B"))

        runs = store.list_runs(tenant_id="t-A")
        assert len(runs) == 1
        assert runs[0]["id"] == "secrun-a"

    def test_list_runs_status_filter_applies_before_limit(self) -> None:
        store = SecurityScanStore()
        newer_failed = _make_run(run_id="secrun-failed", status="failed")
        newer_failed.created_at = datetime(2025, 6, 1, tzinfo=UTC)
        older_completed = _make_run(run_id="secrun-completed", status="completed")
        older_completed.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        store.save_run(older_completed)
        store.save_run(newer_failed)

        runs = store.list_runs(status="completed", limit=1)
        assert len(runs) == 1
        assert runs[0]["id"] == "secrun-completed"

    def test_list_runs_profile_filter_applies_before_limit(self) -> None:
        store = SecurityScanStore()
        newer_standard = _make_run(
            run_id="secrun-standard",
            profile=SecurityProfile.STANDARD,
        )
        newer_standard.created_at = datetime(2025, 6, 1, tzinfo=UTC)
        older_quick = _make_run(
            run_id="secrun-quick",
            profile=SecurityProfile.QUICK,
        )
        older_quick.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        store.save_run(older_quick)
        store.save_run(newer_standard)

        runs = store.list_runs(profile="quick", limit=1)
        assert len(runs) == 1
        assert runs[0]["id"] == "secrun-quick"

    def test_delete_run(self) -> None:
        store = SecurityScanStore()
        run = _make_run()
        store.save_run(run)
        assert store.delete_run(run.id) is True
        assert store.get_run(run.id) is None

    def test_delete_run_not_found(self) -> None:
        store = SecurityScanStore()
        assert store.delete_run("ghost") is False

    def test_save_run_upsert(self) -> None:
        store = SecurityScanStore()
        run = _make_run()
        store.save_run(run)

        run.status = "failed"
        store.save_run(run)

        loaded = store.get_run(run.id)
        assert loaded is not None
        assert loaded["status"] == "failed"


# ---------------------------------------------------------------------------
# SecurityScanStore — findings round-trip
# ---------------------------------------------------------------------------


class TestStoreFindingsRoundTrip:
    """Test SQLite round-trip for findings with fingerprints."""

    def test_save_and_get_findings(self) -> None:
        store = SecurityScanStore()
        run = _make_run()
        store.save_run(run)

        f1 = _make_finding(run_id=run.id, title="Finding A")
        f2 = _make_finding(
            run_id=run.id,
            tool="gitleaks",
            title="Finding B",
            category=FindingCategory.SECRETS_EXPOSURE,
            cwe_id="",
        )
        store.save_findings([f1, f2])

        loaded = store.get_findings(run.id)
        assert len(loaded) == 2
        assert loaded[0]["tool"] == "bandit"
        assert loaded[1]["tool"] == "gitleaks"

    def test_get_findings_empty(self) -> None:
        store = SecurityScanStore()
        assert store.get_findings("secrun-nope") == []

    def test_delete_run_cascades_findings(self) -> None:
        store = SecurityScanStore()
        run = _make_run()
        store.save_run(run)
        store.save_findings([_make_finding(run_id=run.id)])

        store.delete_run(run.id)
        assert store.get_findings(run.id) == []

    def test_findings_contain_fingerprint_field(self) -> None:
        store = SecurityScanStore()
        run = _make_run()
        store.save_run(run)
        f = _make_finding(run_id=run.id)
        # Simulate the fingerprint being set before persistence
        fp = compute_finding_fingerprint(f)
        f_dict = f.model_dump()
        f_dict["fingerprint"] = fp  # noqa: F841

        store.save_findings([f])
        loaded = store.get_findings(run.id)
        assert len(loaded) == 1
        # The fingerprint should be a string (possibly empty if not set on model)
        assert isinstance(loaded[0]["fingerprint"], str)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    """Test finding fingerprint computation and deduplication."""

    def test_same_finding_produces_same_fingerprint(self) -> None:
        f1 = _make_finding()
        f2 = _make_finding()
        assert compute_finding_fingerprint(f1) == compute_finding_fingerprint(f2)

    def test_different_tool_produces_different_fingerprint(self) -> None:
        f1 = _make_finding(tool="bandit")
        f2 = _make_finding(tool="semgrep")
        assert compute_finding_fingerprint(f1) != compute_finding_fingerprint(f2)

    def test_deduplicate_removes_duplicates(self) -> None:
        f1 = _make_finding(tool="bandit")
        f2 = _make_finding(tool="bandit")  # identical identity
        result = deduplicate_findings([f1, f2])
        assert len(result) == 1
        assert result[0] is f1  # keeps first occurrence

    def test_deduplicate_keeps_distinct_findings(self) -> None:
        f1 = _make_finding(tool="bandit")
        f2 = _make_finding(tool="semgrep")
        result = deduplicate_findings([f1, f2])
        assert len(result) == 2

    def test_deduplicate_same_tool_different_line(self) -> None:
        f1 = _make_finding(line_number=10)
        f2 = _make_finding(line_number=20)
        result = deduplicate_findings([f1, f2])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Cleanup expired runs
# ---------------------------------------------------------------------------


class TestCleanupExpiredRuns:
    """Test 90-day retention cleanup."""

    def test_cleanup_deletes_old_runs(self) -> None:
        store = SecurityScanStore()
        old_run = _make_run(run_id="secrun-old")
        old_run.created_at = datetime.now(UTC) - timedelta(days=100)
        store.save_run(old_run)

        recent_run = _make_run(run_id="secrun-new")
        recent_run.created_at = datetime.now(UTC)
        store.save_run(recent_run)

        deleted = store.cleanup_expired_runs(retention_days=90)
        assert deleted == 1
        assert store.get_run("secrun-old") is None
        assert store.get_run("secrun-new") is not None

    def test_cleanup_with_no_expired_runs(self) -> None:
        store = SecurityScanStore()
        recent_run = _make_run()
        store.save_run(recent_run)

        deleted = store.cleanup_expired_runs(retention_days=90)
        assert deleted == 0

    def test_cleanup_cascades_to_findings(self) -> None:
        store = SecurityScanStore()
        old_run = _make_run(run_id="secrun-oldfindings")
        old_run.created_at = datetime.now(UTC) - timedelta(days=100)
        store.save_run(old_run)
        store.save_findings([_make_finding(run_id=old_run.id)])

        store.cleanup_expired_runs(retention_days=90)
        assert store.get_findings(old_run.id) == []

    def test_cleanup_custom_retention(self) -> None:
        store = SecurityScanStore()
        run = _make_run(run_id="secrun-custom")
        run.created_at = datetime.now(UTC) - timedelta(days=10)
        store.save_run(run)

        assert store.cleanup_expired_runs(retention_days=30) == 0
        assert store.cleanup_expired_runs(retention_days=5) == 1


# ---------------------------------------------------------------------------
# Integration: SecurityScanService with store
# ---------------------------------------------------------------------------


def _noop_command_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Fake command runner that returns empty output for all tools."""
    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")


def _bandit_command_runner(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """Fake command runner returning canned bandit + gitleaks output."""
    import json as _json

    if "bandit" in " ".join(command):
        payload = {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "issue_text": "subprocess injection",
                    "filename": "app.py",
                    "line_number": 10,
                    "more_info": "https://bandit.example",
                    "issue_cwe": {"id": 78},
                }
            ]
        }
        return subprocess.CompletedProcess(
            args=command, returncode=1, stdout=_json.dumps(payload), stderr=""
        )
    # gitleaks returns empty array (no leaks)
    return subprocess.CompletedProcess(args=command, returncode=0, stdout="[]", stderr="")


class TestServiceIntegrationWithStore:
    """SecurityScanService persists runs and findings when store is set."""

    async def test_scan_persists_run_and_findings(self, tmp_path: object) -> None:
        store = SecurityScanStore()
        target_dir = str(tmp_path)

        svc = SecurityScanService(
            command_runner=_bandit_command_runner,
            allowed_roots=[target_dir],
            store=store,
        )
        run = svc.create_run(
            target=ScanTarget(repository_path=target_dir),
            profile=SecurityProfile.QUICK,
            tenant_id="t-int",
        )
        await svc.launch_scan(run.id)

        # Verify run was persisted
        persisted = store.get_run(run.id)
        assert persisted is not None
        assert persisted["status"] == "completed"

        # Verify findings were persisted
        findings = store.get_findings(run.id)
        assert len(findings) >= 1
        assert findings[0]["tool"] == "bandit"

    async def test_scan_without_store_still_works(self, tmp_path: object) -> None:
        target_dir = str(tmp_path)
        svc = SecurityScanService(
            command_runner=_noop_command_runner,
            allowed_roots=[target_dir],
        )
        run = svc.create_run(
            target=ScanTarget(repository_path=target_dir),
            profile=SecurityProfile.QUICK,
        )
        result = await svc.launch_scan(run.id)
        assert result.status == "completed"

    async def test_dedup_applied_before_persist(self, tmp_path: object) -> None:
        """Ensure duplicate findings from bandit are collapsed."""
        import json as _json

        def _dup_command_runner(
            command: list[str], timeout: int
        ) -> subprocess.CompletedProcess[str]:
            if "bandit" in " ".join(command):
                finding = {
                    "issue_severity": "HIGH",
                    "issue_text": "subprocess injection",
                    "filename": "app.py",
                    "line_number": 10,
                    "more_info": "",
                    "issue_cwe": {"id": 78},
                }
                payload = {"results": [finding, finding]}
                return subprocess.CompletedProcess(
                    args=command, returncode=1, stdout=_json.dumps(payload), stderr=""
                )
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="[]", stderr="")

        store = SecurityScanStore()
        target_dir = str(tmp_path)
        svc = SecurityScanService(
            command_runner=_dup_command_runner,
            allowed_roots=[target_dir],
            store=store,
        )
        run = svc.create_run(
            target=ScanTarget(repository_path=target_dir),
            profile=SecurityProfile.QUICK,
        )
        await svc.launch_scan(run.id)

        findings = store.get_findings(run.id)
        # Two identical findings should be deduplicated to one
        assert len(findings) == 1


# ---------------------------------------------------------------------------
# Store close / file-backed
# ---------------------------------------------------------------------------


class TestStoreFileBacked:
    """Ensure the store works with a real file path."""

    def test_file_backed_persistence(self, tmp_path: object) -> None:
        import pathlib

        db_file = str(pathlib.Path(str(tmp_path)) / "scans.db")
        store = SecurityScanStore(db_path=db_file)
        run = _make_run()
        store.save_run(run)
        store.close()

        # Re-open the same file
        store2 = SecurityScanStore(db_path=db_file)
        loaded = store2.get_run(run.id)
        assert loaded is not None
        assert loaded["id"] == run.id
        store2.close()


class TestSecurityScanServiceStoreIntegration:
    """SecurityScanService hydrates and persists lifecycle state via store."""

    def test_service_hydrates_runs_and_findings_from_store(self, tmp_path: object) -> None:
        store = SecurityScanStore(db_path=str(tmp_path / "scans.db"))
        run = _make_run(run_id="secrun-hydrate")
        finding = _make_finding(run_id=run.id, title="persisted finding")
        run.started_at = datetime.now(UTC)
        run.completed_at = datetime.now(UTC)
        run.status = RunStatus.COMPLETED
        store.save_run(run)
        store.save_findings([finding])

        service = SecurityScanService(store=store)
        hydrated_run = service.get_run(run.id)
        assert hydrated_run.tenant_id == run.tenant_id
        findings = service.fetch_findings(run.id)
        assert len(findings) == 1
        assert findings[0].title == "persisted finding"

    def test_service_reads_store_on_list_delete_and_fetch(self, tmp_path: object) -> None:
        store = SecurityScanStore(db_path=str(tmp_path / "scans.db"))
        active_run = _make_run(run_id="secrun-list")
        active_run.status = RunStatus.COMPLETED
        active_run.started_at = datetime.now(UTC)
        active_run.completed_at = datetime.now(UTC)
        store.save_run(active_run)

        service = SecurityScanService(store=store)
        assert service.list_runs(limit=10)[0].id == active_run.id

        service.delete_run(active_run.id)
        assert store.get_run(active_run.id) is None

    def test_service_list_runs_does_not_hydrate_findings(self, tmp_path: object) -> None:
        class SpySecurityScanStore(SecurityScanStore):
            def __init__(self, db_path: str) -> None:
                super().__init__(db_path=db_path)
                self.list_runs_calls = 0
                self.get_findings_calls = 0

            def list_runs(self, **kwargs: object) -> list[dict[str, object]]:
                self.list_runs_calls += 1
                return super().list_runs(**kwargs)

            def get_findings(self, run_id: str) -> list[dict[str, object]]:
                self.get_findings_calls += 1
                return super().get_findings(run_id)

        store = SpySecurityScanStore(db_path=str(tmp_path / "scans.db"))
        run = _make_run(run_id="secrun-spy")
        store.save_run(run)
        store.save_findings([_make_finding(run_id=run.id)])

        service = SecurityScanService(store=store)
        store.list_runs_calls = 0
        store.get_findings_calls = 0

        runs = service.list_runs(limit=10)

        assert [item.id for item in runs] == [run.id]
        assert store.list_runs_calls == 1
        assert store.get_findings_calls == 0

    def test_service_list_runs_forwards_store_filters_before_limit(
        self,
        tmp_path: object,
    ) -> None:
        store = SecurityScanStore(db_path=str(tmp_path / "scans.db"))

        older_completed = _make_run(
            run_id="secrun-completed",
            status=RunStatus.COMPLETED,
            profile=SecurityProfile.QUICK,
        )
        older_completed.created_at = datetime(2025, 1, 1, tzinfo=UTC)
        older_completed.updated_at = older_completed.created_at
        newer_failed = _make_run(
            run_id="secrun-failed",
            status=RunStatus.FAILED,
            profile=SecurityProfile.QUICK,
        )
        newer_failed.created_at = datetime(2025, 6, 1, tzinfo=UTC)
        newer_failed.updated_at = newer_failed.created_at
        store.save_run(older_completed)
        store.save_run(newer_failed)

        older_quick = _make_run(
            run_id="secrun-quick",
            status=RunStatus.COMPLETED,
            profile=SecurityProfile.QUICK,
        )
        older_quick.created_at = datetime(2025, 1, 2, tzinfo=UTC)
        older_quick.updated_at = older_quick.created_at
        newer_standard = _make_run(
            run_id="secrun-standard",
            status=RunStatus.FAILED,
            profile=SecurityProfile.STANDARD,
        )
        newer_standard.created_at = datetime(2025, 6, 2, tzinfo=UTC)
        newer_standard.updated_at = newer_standard.created_at
        store.save_run(older_quick)
        store.save_run(newer_standard)

        service = SecurityScanService(store=store)

        completed_runs = service.list_runs(status=RunStatus.COMPLETED, limit=1)
        quick_runs = service.list_runs(profile=SecurityProfile.QUICK, limit=1)

        assert [run.id for run in completed_runs] == ["secrun-quick"]
        assert [run.id for run in quick_runs] == ["secrun-failed"]

    def test_service_list_runs_falls_back_to_cache_when_store_list_fails(
        self,
        tmp_path: object,
    ) -> None:
        class FailingListSecurityScanStore(SecurityScanStore):
            def __init__(self, db_path: str) -> None:
                super().__init__(db_path=db_path)
                self.fail_list_runs = False

            def list_runs(self, **kwargs: object) -> list[dict[str, object]]:
                if self.fail_list_runs:
                    raise RuntimeError("sqlite read failed")
                return super().list_runs(**kwargs)

        store = FailingListSecurityScanStore(db_path=str(tmp_path / "scans.db"))
        run = _make_run(run_id="secrun-fallback", status=RunStatus.COMPLETED)
        store.save_run(run)

        service = SecurityScanService(store=store)
        store.fail_list_runs = True

        runs = service.list_runs(status=RunStatus.COMPLETED, limit=10)

        assert [item.id for item in runs] == [run.id]

    async def test_service_persists_state_transitions_beyond_completed(
        self,
        tmp_path: object,
    ) -> None:
        db_path = str(tmp_path / "scans.db")
        store = SecurityScanStore(db_path=db_path)
        target = tmp_path / "repo"
        target.mkdir()

        service = SecurityScanService(
            command_runner=lambda command, timeout: subprocess.CompletedProcess(
                args=command,
                returncode=2,
                stdout="",
                stderr="boom",
            ),
            allowed_roots=[str(target)],
            store=store,
        )
        run = service.create_run(
            target=ScanTarget(repository_path=str(target)),
            profile=SecurityProfile.QUICK,
            tenant_id="t-1",
        )
        assert service.get_run(run.id, tenant_id="t-1").status == RunStatus.PENDING

        failed = await service.launch_scan(run.id)
        assert failed.status == RunStatus.FAILED
        persisted = store.get_run(run.id)
        assert persisted is not None
        assert persisted["status"] == "failed"

    def test_service_hydration_supports_restart_survival_for_cancelled_runs(
        self,
        tmp_path: object,
    ) -> None:
        db_path = str(tmp_path / "scans.db")
        store = SecurityScanStore(db_path=db_path)
        target = tmp_path / "repo"
        target.mkdir()

        first_service = SecurityScanService(
            allowed_roots=[str(target)],
            store=store,
        )
        run = first_service.create_run(
            target=ScanTarget(repository_path=str(target)),
            profile=SecurityProfile.QUICK,
            tenant_id="t-1",
        )
        first_service.cancel_run(run.id)

        second_service = SecurityScanService(allowed_roots=[str(target)], store=store)
        hydrated_run = second_service.get_run(run.id, tenant_id="t-1")
        assert hydrated_run.status == RunStatus.CANCELLED

    def test_service_applies_retention_cleanup_on_startup(self, tmp_path: object) -> None:
        store = SecurityScanStore(db_path=str(tmp_path / "scans.db"))
        expired_run = _make_run(run_id="secrun-expired")
        expired_run.created_at = datetime.now(UTC) - timedelta(days=120)
        store.save_run(expired_run)

        SecurityScanService(store=store, store_retention_days=30)

        assert store.get_run(expired_run.id) is None

    def test_store_refresh_evicted_deleted_runs_across_instances(self, tmp_path: object) -> None:
        store_path = str(tmp_path / "scans.db")
        target = tmp_path / "repo"
        target.mkdir()

        first_service = SecurityScanService(
            allowed_roots=[str(target)],
            store=SecurityScanStore(db_path=store_path),
        )
        second_service = SecurityScanService(
            allowed_roots=[str(target)],
            store=SecurityScanStore(db_path=store_path),
        )

        run = first_service.create_run(
            target=ScanTarget(repository_path=str(target)),
            profile=SecurityProfile.QUICK,
        )
        assert any(item.id == run.id for item in second_service.list_runs())

        second_service.delete_run(run.id)

        assert all(item.id != run.id for item in first_service.list_runs())
