"""Phase 28 Stage 1 tests for component security backend surfaces."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import component_security
from agent33.component_security.mcp_scanner import (
    MCPSecurityScanner,
    MCPServerConfig,
    MCPTransport,
)
from agent33.component_security.models import (
    FindingCategory,
    FindingSeverity,
    FindingsSummary,
    RunStatus,
    ScanTarget,
    SecurityFinding,
    SecurityProfile,
    SecurityRun,
)
from agent33.component_security.persistence import SecurityScanStore
from agent33.main import app
from agent33.security.auth import create_access_token
from agent33.services.security_scan import SecurityScanService

if TYPE_CHECKING:
    from pathlib import Path


def _fake_completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _default_command_runner(
    command: list[str], _timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    if "bandit" in " ".join(command):
        return _fake_completed('{"results": []}')
    if command and command[0] == "gitleaks":
        return _fake_completed("[]")
    if "pip_audit" in " ".join(command):
        return _fake_completed('{"dependencies": []}')
    if command and command[0] == "semgrep":
        return _fake_completed('{"results": []}')
    return _fake_completed("")


@pytest.fixture(autouse=True)
def reset_component_security_service() -> None:
    service = component_security.get_component_security_service()
    service._runs.clear()
    service._findings.clear()
    service._command_runner = _default_command_runner
    service._allowed_roots = []
    yield
    service = component_security.get_component_security_service()
    service._runs.clear()
    service._findings.clear()
    service._command_runner = _default_command_runner
    service._allowed_roots = []


@pytest.fixture
def writer_client() -> TestClient:
    token = create_access_token(
        "component-security-writer",
        scopes=["component-security:read", "component-security:write"],
    )
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def reader_client() -> TestClient:
    token = create_access_token("component-security-reader", scopes=["component-security:read"])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def no_scope_client() -> TestClient:
    token = create_access_token("component-security-none", scopes=[])
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


class TestComponentSecurityModels:
    def test_run_defaults(self) -> None:
        run = SecurityRun(
            profile=SecurityProfile.QUICK,
            target=ScanTarget(repository_path="."),
        )
        assert run.id.startswith("secrun-")
        assert run.status == RunStatus.PENDING
        assert run.findings_count == 0
        assert run.duration_seconds == 0

    def test_findings_summary_aggregation(self) -> None:
        findings = [
            SecurityFinding(
                run_id="secrun-1",
                severity=FindingSeverity.HIGH,
                category=FindingCategory.CODE_QUALITY,
                title="a",
                description="a",
                tool="bandit",
            ),
            SecurityFinding(
                run_id="secrun-1",
                severity=FindingSeverity.LOW,
                category=FindingCategory.SECRETS_EXPOSURE,
                title="b",
                description="b",
                tool="gitleaks",
            ),
        ]
        summary = FindingsSummary.from_findings(findings)
        assert summary.high == 1
        assert summary.low == 1
        assert summary.total == 2


class TestSecurityScanService:
    async def test_launch_quick_scan_collects_findings(self, tmp_path: Path) -> None:
        def command_runner(
            command: list[str], _timeout_seconds: int
        ) -> subprocess.CompletedProcess[str]:
            if "bandit" in " ".join(command):
                return _fake_completed(
                    json.dumps(
                        {
                            "results": [
                                {
                                    "issue_severity": "HIGH",
                                    "issue_text": "Use of subprocess with shell=True",
                                    "filename": "app.py",
                                    "line_number": 12,
                                    "issue_cwe": {"id": "78"},
                                }
                            ]
                        }
                    ),
                    returncode=1,
                )
            return _fake_completed(
                json.dumps(
                    [
                        {
                            "RuleID": "generic-api-key",
                            "Description": "Detected a Generic API Key",
                            "File": "config.py",
                            "StartLine": 10,
                        }
                    ]
                )
            )

        service = SecurityScanService(command_runner=command_runner)
        run = service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.QUICK,
        )
        completed = await service.launch_scan(run.id)

        assert completed.status == RunStatus.COMPLETED
        assert completed.findings_count == 2
        assert completed.findings_summary.high == 2
        findings = service.fetch_findings(run.id)
        assert len(findings) == 2
        assert {finding.tool for finding in findings} == {"bandit", "gitleaks"}

    async def test_launch_scan_fails_for_missing_target(self) -> None:
        service = SecurityScanService(command_runner=_default_command_runner)
        run = service.create_run(
            target=ScanTarget(repository_path="D:\\missing-target"),
            profile=SecurityProfile.QUICK,
        )
        failed = await service.launch_scan(run.id)
        assert failed.status == RunStatus.FAILED
        assert "does not exist" in failed.error_message

    async def test_launch_scan_rejects_target_outside_allowed_roots(self, tmp_path: Path) -> None:
        allowed_root = tmp_path / "allowed"
        outside_root = tmp_path / "outside"
        allowed_root.mkdir()
        outside_root.mkdir()
        service = SecurityScanService(
            command_runner=_default_command_runner,
            allowed_roots=[str(allowed_root)],
        )
        run = service.create_run(
            target=ScanTarget(repository_path=str(outside_root)),
            profile=SecurityProfile.QUICK,
        )

        failed = await service.launch_scan(run.id)
        assert failed.status == RunStatus.FAILED
        assert "outside allowed directories" in failed.error_message

    async def test_cancelled_run_not_overwritten_by_completed_state(self, tmp_path: Path) -> None:
        run_id = ""

        def command_runner(
            command: list[str], _timeout_seconds: int
        ) -> subprocess.CompletedProcess[str]:
            if "bandit" in " ".join(command):
                service.cancel_run(run_id)
                return _fake_completed('{"results": []}')
            return _fake_completed("[]")

        service = SecurityScanService(command_runner=command_runner)
        target = tmp_path / "repo"
        target.mkdir()
        run = service.create_run(
            target=ScanTarget(repository_path=str(target)),
            profile=SecurityProfile.QUICK,
        )
        run_id = run.id

        cancelled = await service.launch_scan(run.id)
        assert cancelled.status == RunStatus.CANCELLED
        assert cancelled.completed_at is not None

    async def test_standard_profile_executes_additional_scanners(self, tmp_path: Path) -> None:
        service = SecurityScanService(command_runner=_default_command_runner)
        run = service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.STANDARD,
        )
        completed = await service.launch_scan(run.id)
        assert completed.status == RunStatus.COMPLETED
        assert completed.metadata.tools_executed == ["bandit", "gitleaks", "pip-audit"]

    async def test_deep_profile_executes_semgrep(self, tmp_path: Path) -> None:
        service = SecurityScanService(command_runner=_default_command_runner)
        run = service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.DEEP,
        )
        completed = await service.launch_scan(run.id)
        assert completed.status == RunStatus.COMPLETED
        assert completed.metadata.tools_executed == [
            "bandit",
            "gitleaks",
            "pip-audit",
            "semgrep",
        ]

    async def test_optional_tool_missing_adds_warning(self, tmp_path: Path) -> None:
        def missing_semgrep_runner(
            command: list[str], _timeout_seconds: int
        ) -> subprocess.CompletedProcess[str]:
            if "bandit" in " ".join(command):
                return _fake_completed('{"results": []}')
            if command and command[0] == "gitleaks":
                return _fake_completed("[]")
            if "pip_audit" in " ".join(command):
                return _fake_completed('{"dependencies": []}')
            if command and command[0] == "semgrep":
                raise FileNotFoundError
            return _fake_completed("")

        service = SecurityScanService(command_runner=missing_semgrep_runner)
        run = service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.DEEP,
        )
        completed = await service.launch_scan(run.id)
        assert completed.status == RunStatus.COMPLETED
        assert completed.metadata.tools_executed[-1] == "semgrep"
        assert completed.metadata.tool_warnings

    async def test_mcp_servers_called_during_launch_scan_and_findings_merged(
        self, tmp_path: Path
    ) -> None:
        """Registered MCP security servers are invoked by launch_scan() and their
        findings are merged into the run's finding list."""
        mcp_finding = SecurityFinding(
            run_id="placeholder",
            severity=FindingSeverity.HIGH,
            category=FindingCategory.INJECTION_RISK,
            title="MCP detected injection risk",
            description="eval() usage detected by MCP scanner",
            tool="mcp-test-server",
        )

        # Build a fake MCPSecurityScanner whose scan() coroutine returns one finding
        mock_scanner = MagicMock(spec=MCPSecurityScanner)
        fake_server = MCPServerConfig(
            name="mcp-test-server",
            transport=MCPTransport.STDIO,
            command="fake-cmd",
        )
        mock_scanner.list_servers.return_value = [fake_server]

        async def _fake_scan(server_name: str, target: str, run_id: str) -> list[SecurityFinding]:
            # Return a finding with the correct run_id
            return [mcp_finding.model_copy(update={"run_id": run_id})]

        mock_scanner.scan = _fake_scan

        service = SecurityScanService(
            command_runner=_default_command_runner,
            mcp_scanner=mock_scanner,
        )
        run = service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.QUICK,
        )
        completed = await service.launch_scan(run.id)

        assert completed.status == RunStatus.COMPLETED
        # Standard tools executed plus the MCP server
        assert "mcp:mcp-test-server" in completed.metadata.tools_executed
        # MCP finding must be in the final findings list
        findings = service.fetch_findings(run.id)
        mcp_findings = [f for f in findings if f.tool == "mcp-test-server"]
        assert len(mcp_findings) == 1
        assert mcp_findings[0].title == "MCP detected injection risk"
        assert completed.findings_count == len(findings)

    async def test_mcp_server_failure_is_non_fatal_and_adds_warning(self, tmp_path: Path) -> None:
        """If an MCP server call raises, the run still completes with a warning."""
        mock_scanner = MagicMock(spec=MCPSecurityScanner)
        fake_server = MCPServerConfig(
            name="flaky-mcp",
            transport=MCPTransport.STDIO,
            command="fake-cmd",
        )
        mock_scanner.list_servers.return_value = [fake_server]

        async def _failing_scan(
            server_name: str, target: str, run_id: str
        ) -> list[SecurityFinding]:
            raise RuntimeError("connection refused")

        mock_scanner.scan = _failing_scan

        service = SecurityScanService(
            command_runner=_default_command_runner,
            mcp_scanner=mock_scanner,
        )
        run = service.create_run(
            target=ScanTarget(repository_path=str(tmp_path)),
            profile=SecurityProfile.QUICK,
        )
        completed = await service.launch_scan(run.id)

        assert completed.status == RunStatus.COMPLETED
        # The MCP server should NOT appear in tools_executed
        assert "mcp:flaky-mcp" not in completed.metadata.tools_executed
        # But a warning must be present
        assert any("flaky-mcp" in w for w in completed.metadata.tool_warnings)


class TestComponentSecurityApi:
    def test_create_run_pending_when_execute_now_false(
        self, writer_client: TestClient, tmp_path: Path
    ) -> None:
        response = writer_client.post(
            "/v1/component-security/runs",
            json={
                "target": {"repository_path": str(tmp_path)},
                "profile": "quick",
                "execute_now": False,
            },
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["status"] == "pending"
        assert payload["findings_count"] == 0

    def test_create_run_executes_quick_profile(
        self, writer_client: TestClient, tmp_path: Path
    ) -> None:
        response = writer_client.post(
            "/v1/component-security/runs",
            json={"target": {"repository_path": str(tmp_path)}, "profile": "quick"},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["metadata"]["tools_executed"] == ["bandit", "gitleaks"]

    def test_create_run_executes_standard_profile(
        self, writer_client: TestClient, tmp_path: Path
    ) -> None:
        response = writer_client.post(
            "/v1/component-security/runs",
            json={"target": {"repository_path": str(tmp_path)}, "profile": "standard"},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["status"] == "completed"
        assert payload["metadata"]["tools_executed"] == ["bandit", "gitleaks", "pip-audit"]

    def test_list_get_and_status_endpoints(
        self, writer_client: TestClient, reader_client: TestClient, tmp_path: Path
    ) -> None:
        create_response = writer_client.post(
            "/v1/component-security/runs",
            json={"target": {"repository_path": str(tmp_path)}, "execute_now": False},
        )
        run_id = create_response.json()["id"]

        list_response = reader_client.get("/v1/component-security/runs")
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        get_response = reader_client.get(f"/v1/component-security/runs/{run_id}")
        assert get_response.status_code == 200
        assert get_response.json()["id"] == run_id

        status_response = reader_client.get(f"/v1/component-security/runs/{run_id}/status")
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "pending"

    def test_findings_endpoint_with_filter(
        self, writer_client: TestClient, reader_client: TestClient, tmp_path: Path
    ) -> None:
        create_response = writer_client.post(
            "/v1/component-security/runs",
            json={"target": {"repository_path": str(tmp_path)}, "profile": "quick"},
        )
        run_id = create_response.json()["id"]

        findings_response = reader_client.get(
            f"/v1/component-security/runs/{run_id}/findings?min_severity=high"
        )
        assert findings_response.status_code == 200
        payload = findings_response.json()
        assert payload["total_count"] == 0
        assert payload["findings"] == []

    def test_cancel_terminal_run_returns_409(
        self, writer_client: TestClient, tmp_path: Path
    ) -> None:
        create_response = writer_client.post(
            "/v1/component-security/runs",
            json={"target": {"repository_path": str(tmp_path)}, "profile": "quick"},
        )
        run_id = create_response.json()["id"]

        cancel_response = writer_client.post(f"/v1/component-security/runs/{run_id}/cancel")
        assert cancel_response.status_code == 409

    def test_delete_run_then_get_returns_404(
        self, writer_client: TestClient, reader_client: TestClient, tmp_path: Path
    ) -> None:
        create_response = writer_client.post(
            "/v1/component-security/runs",
            json={"target": {"repository_path": str(tmp_path)}, "execute_now": False},
        )
        run_id = create_response.json()["id"]

        delete_response = writer_client.delete(f"/v1/component-security/runs/{run_id}")
        assert delete_response.status_code == 200

        get_response = reader_client.get(f"/v1/component-security/runs/{run_id}")
        assert get_response.status_code == 404

    def test_scope_enforcement_for_missing_permissions(
        self, no_scope_client: TestClient, tmp_path: Path
    ) -> None:
        create_response = no_scope_client.post(
            "/v1/component-security/runs",
            json={"target": {"repository_path": str(tmp_path)}, "profile": "quick"},
        )
        assert create_response.status_code == 403

        list_response = no_scope_client.get("/v1/component-security/runs")
        assert list_response.status_code == 403

    def test_llm_scan_invokes_adapter_backed_scanners(
        self,
        writer_client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        create_response = writer_client.post(
            "/v1/component-security/runs",
            json={
                "target": {"repository_path": str(tmp_path)},
                "profile": "deep",
                "requested_by": "reviewer",
                "execute_now": False,
            },
        )
        run_id = create_response.json()["id"]

        def _scan_prompt_safety(
            text: str, *, run_id: str = "", source: str = ""
        ) -> list[SecurityFinding]:
            return [
                SecurityFinding(
                    run_id=run_id,
                    severity=FindingSeverity.LOW,
                    category=FindingCategory.PROMPT_INJECTION,
                    title=f"prompt:{source}",
                    description=text,
                    tool="llm-security",
                )
            ]

        def _scan_model_behavior(model_name: str, *, run_id: str = "") -> list[SecurityFinding]:
            return [
                SecurityFinding(
                    run_id=run_id,
                    severity=FindingSeverity.MEDIUM,
                    category=FindingCategory.MODEL_SECURITY,
                    title=model_name,
                    description="garak",
                    tool="garak",
                )
            ]

        monkeypatch.setattr(
            component_security._llm_scanner, "scan_prompt_safety", _scan_prompt_safety
        )
        monkeypatch.setattr(
            component_security._llm_scanner, "scan_model_behavior", _scan_model_behavior
        )

        response = writer_client.post(f"/v1/component-security/runs/{run_id}/llm-scan")

        assert response.status_code == 200
        payload = response.json()
        assert payload["llm_findings"] >= 2
        assert payload["total_findings"] == payload["llm_findings"]

    def test_llm_scan_skips_model_behavior_for_non_deep_profiles(
        self,
        writer_client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        create_response = writer_client.post(
            "/v1/component-security/runs",
            json={
                "target": {"repository_path": str(tmp_path)},
                "profile": "quick",
                "requested_by": "reviewer",
                "execute_now": False,
            },
        )
        run_id = create_response.json()["id"]

        def _scan_prompt_safety(
            text: str, *, run_id: str = "", source: str = ""
        ) -> list[SecurityFinding]:
            return [
                SecurityFinding(
                    run_id=run_id,
                    severity=FindingSeverity.LOW,
                    category=FindingCategory.PROMPT_INJECTION,
                    title=f"prompt:{source}",
                    description=text,
                    tool="llm-security",
                )
            ]

        def _scan_model_behavior(model_name: str, *, run_id: str = "") -> list[SecurityFinding]:
            raise AssertionError(f"model probes should be skipped for quick profile: {model_name}")

        monkeypatch.setattr(
            component_security._llm_scanner, "scan_prompt_safety", _scan_prompt_safety
        )
        monkeypatch.setattr(
            component_security._llm_scanner, "scan_model_behavior", _scan_model_behavior
        )

        response = writer_client.post(f"/v1/component-security/runs/{run_id}/llm-scan")

        assert response.status_code == 200
        payload = response.json()
        assert payload["llm_findings"] >= 1
        assert payload["total_findings"] == payload["llm_findings"]

    def test_llm_scan_run_summary_persists_across_restart(
        self,
        writer_client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store_path = tmp_path / "component-security-scans.sqlite3"
        service = SecurityScanService(
            command_runner=_default_command_runner,
            allowed_roots=[str(tmp_path)],
            store=SecurityScanStore(db_path=str(store_path)),
        )
        monkeypatch.setattr(component_security, "_service", service)

        create_response = writer_client.post(
            "/v1/component-security/runs",
            json={
                "target": {"repository_path": str(tmp_path)},
                "profile": "quick",
                "requested_by": "reviewer",
                "session_id": "sess-123",
                "execute_now": False,
            },
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["id"]

        def _scan_prompt_safety(
            text: str, *, run_id: str = "", source: str = ""
        ) -> list[SecurityFinding]:
            return [
                SecurityFinding(
                    run_id=run_id,
                    severity=FindingSeverity.LOW,
                    category=FindingCategory.PROMPT_INJECTION,
                    title=f"prompt:{source}",
                    description=text,
                    tool="llm-security",
                )
            ]

        def _scan_model_behavior(model_name: str, *, run_id: str = "") -> list[SecurityFinding]:
            return [
                SecurityFinding(
                    run_id=run_id,
                    severity=FindingSeverity.MEDIUM,
                    category=FindingCategory.MODEL_SECURITY,
                    title=model_name,
                    description="garak",
                    tool="garak",
                )
            ]

        monkeypatch.setattr(
            component_security._llm_scanner,
            "scan_prompt_safety",
            _scan_prompt_safety,
        )
        monkeypatch.setattr(
            component_security._llm_scanner,
            "scan_model_behavior",
            _scan_model_behavior,
        )
        llm_response = writer_client.post(f"/v1/component-security/runs/{run_id}/llm-scan")
        assert llm_response.status_code == 200

        restarted_service = SecurityScanService(
            command_runner=_default_command_runner,
            allowed_roots=[str(tmp_path)],
            store=SecurityScanStore(db_path=str(store_path)),
        )
        monkeypatch.setattr(component_security, "_service", restarted_service)

        run_response = writer_client.get(f"/v1/component-security/runs/{run_id}")
        assert run_response.status_code == 200
        payload = run_response.json()
        assert payload["findings_count"] == llm_response.json()["total_findings"]
        assert payload["metadata"]["requested_by"] == "reviewer"
        assert payload["metadata"]["session_id"] == "sess-123"

        findings_response = writer_client.get(f"/v1/component-security/runs/{run_id}/findings")
        assert findings_response.status_code == 200
        assert findings_response.json()["total_count"] == llm_response.json()["total_findings"]

        sarif_response = writer_client.get(f"/v1/component-security/runs/{run_id}/sarif")
        assert sarif_response.status_code == 200
        assert sarif_response.json()["runs"]

    def test_list_runs_read_persists_from_store_restart(
        self,
        writer_client: TestClient,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        store_path = tmp_path / "component-security-scans.sqlite3"
        first_service = SecurityScanService(
            command_runner=_default_command_runner,
            allowed_roots=[str(tmp_path)],
            store=SecurityScanStore(db_path=str(store_path)),
        )
        monkeypatch.setattr(component_security, "_service", first_service)
        create_response = writer_client.post(
            "/v1/component-security/runs",
            json={
                "target": {
                    "repository_path": str(tmp_path),
                    "branch": "feature/persisted",
                },
                "profile": "quick",
                "execute_now": False,
            },
        )
        assert create_response.status_code == 201
        run_id = create_response.json()["id"]

        second_service = SecurityScanService(
            command_runner=_default_command_runner,
            allowed_roots=[str(tmp_path)],
            store=SecurityScanStore(db_path=str(store_path)),
        )
        monkeypatch.setattr(component_security, "_service", second_service)
        list_response = writer_client.get("/v1/component-security/runs")
        assert list_response.status_code == 200
        run_ids = {run["id"] for run in list_response.json()}
        assert run_id in run_ids

        get_response = writer_client.get(f"/v1/component-security/runs/{run_id}")
        assert get_response.status_code == 200
        assert get_response.json()["target"]["branch"] == "feature/persisted"

    def test_sarif_route_returns_unavailable_when_service_missing(
        self,
        writer_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        original_app_service = getattr(app.state, "security_scan_service", None)
        monkeypatch.setattr(component_security, "_service", None)
        with monkeypatch.context() as ctx:
            if hasattr(app.state, "security_scan_service"):
                ctx.delattr(app.state, "security_scan_service", raising=False)
            response = writer_client.get("/v1/component-security/runs/secrun-missing/sarif")

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["status"] == "unavailable"
        assert detail["service"] == "component-security"
        assert "Initialize component security service" in detail["required_action"]
        if original_app_service is not None:
            app.state.security_scan_service = original_app_service

    def test_run_routes_return_unavailable_when_service_missing(
        self,
        writer_client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        original_app_service = getattr(app.state, "security_scan_service", None)
        original_status = getattr(app.state, "security_scan_status", None)
        monkeypatch.setattr(component_security, "_service", None)
        with monkeypatch.context() as ctx:
            ctx.delattr(app.state, "security_scan_service", raising=False)
            app.state.security_scan_status = {
                "status": "unavailable",
                "service": "component-security",
                "reason": "store open failed",
            }
            response = writer_client.post(
                "/v1/component-security/runs",
                json={"target": {"repository_path": str(tmp_path)}, "execute_now": False},
            )
            health = writer_client.get("/v1/component-security/health")

        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["status"] == "unavailable"
        assert detail["service"] == "component-security"
        assert detail["reason"] == "store open failed"
        assert "scan APIs" in detail["required_action"]
        assert health.status_code == 200
        assert health.json()["initialized"] is False
        assert health.json()["reason"] == "store open failed"
        if original_app_service is not None:
            app.state.security_scan_service = original_app_service
        if original_status is not None:
            app.state.security_scan_status = original_status
