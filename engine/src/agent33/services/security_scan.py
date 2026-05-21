"""Security scan service for component security operations."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from agent33.component_security.models import (
    FindingCategory,
    FindingSeverity,
    FindingsSummary,
    RunStatus,
    ScanOptions,
    ScanTarget,
    SecurityFinding,
    SecurityProfile,
    SecurityRun,
)

logger = structlog.get_logger()

if TYPE_CHECKING:
    from collections.abc import Callable

    from agent33.component_security.mcp_scanner import MCPSecurityScanner
    from agent33.component_security.persistence import SecurityScanStore

_TERMINAL_STATES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.TIMEOUT,
    }
)
_SEVERITY_ORDER = {
    FindingSeverity.INFO: 0,
    FindingSeverity.LOW: 1,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.HIGH: 3,
    FindingSeverity.CRITICAL: 4,
}


class SecurityScanError(Exception):
    """Base service error for component security operations."""


class RunNotFoundError(SecurityScanError):
    """Raised when the requested run does not exist."""


class RunStateError(SecurityScanError):
    """Raised for invalid state transitions."""


class ToolExecutionError(SecurityScanError):
    """Raised when scanner command execution fails."""


class SecurityScanService:
    """In-memory service for component security run lifecycle and quick profile scans."""

    def __init__(
        self,
        command_runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] | None = None,
        allowed_roots: list[str] | None = None,
        store: SecurityScanStore | None = None,
        store_retention_days: int | None = None,
        mcp_scanner: MCPSecurityScanner | None = None,
    ) -> None:
        self._runs: dict[str, SecurityRun] = {}
        self._findings: dict[str, list[SecurityFinding]] = {}
        self._command_runner = command_runner or self._run_command
        self._allowed_roots = [Path(root).resolve() for root in (allowed_roots or [])]
        self._store = store
        self._store_retention_days = store_retention_days
        self._mcp_scanner = mcp_scanner
        self._apply_store_retention()
        self._load_persisted_state()

    def create_run(
        self,
        *,
        target: ScanTarget,
        profile: SecurityProfile,
        options: ScanOptions | None = None,
        tenant_id: str = "",
        requested_by: str = "",
        session_id: str = "",
        release_candidate_id: str = "",
    ) -> SecurityRun:
        """Create and store a new security run."""
        run = SecurityRun(
            tenant_id=tenant_id,
            profile=profile,
            target=target,
            options=options or ScanOptions(),
        )
        run.metadata.requested_by = requested_by
        run.metadata.session_id = session_id
        run.metadata.release_candidate_id = release_candidate_id
        self._runs[run.id] = run
        self._findings[run.id] = []
        self._persist(run, findings=[])
        logger.info("component_security_run_created", run_id=run.id, profile=profile.value)
        return run

    def list_runs(
        self,
        *,
        tenant_id: str | None = None,
        status: RunStatus | None = None,
        profile: SecurityProfile | None = None,
        limit: int = 50,
    ) -> list[SecurityRun]:
        """List runs with optional tenant/status/profile filters."""
        if self._store is not None:
            try:
                persisted_rows = self._store.list_runs(
                    tenant_id=tenant_id,
                    status=status.value if status is not None else None,
                    profile=profile.value if profile is not None else None,
                    limit=limit,
                )
            except Exception:
                logger.exception("security_scan_store_list_failed")
            else:
                runs: list[SecurityRun] = []
                for row in persisted_rows:
                    run = self._run_from_store_row(row)
                    if run is None:
                        continue
                    self._runs[run.id] = run
                    runs.append(run)
                return runs
        runs = list(self._runs.values())
        if tenant_id:
            runs = [run for run in runs if run.tenant_id == tenant_id]
        if status is not None:
            runs = [run for run in runs if run.status == status]
        if profile is not None:
            runs = [run for run in runs if run.profile == profile]
        runs.sort(key=lambda run: run.created_at, reverse=True)
        return runs[:limit]

    def get_run(self, run_id: str, *, tenant_id: str | None = None) -> SecurityRun:
        """Get a run by ID with optional tenant check."""
        run = (
            self._load_run_from_store(run_id)
            if self._store is not None
            else self._runs.get(run_id)
        )
        if run is None:
            raise RunNotFoundError(f"Component security run not found: {run_id}")
        if tenant_id and run.tenant_id != tenant_id:
            raise RunNotFoundError(f"Component security run not found: {run_id}")
        return run

    async def launch_scan(self, run_id: str, *, tenant_id: str | None = None) -> SecurityRun:
        """Execute scanners for the requested profile and persist findings."""
        run = self.get_run(run_id, tenant_id=tenant_id)
        if run.status != RunStatus.PENDING:
            raise RunStateError(f"Run {run.id} cannot start from state {run.status.value}")

        run.status = RunStatus.RUNNING
        run.touch()
        run.started_at = run.updated_at
        self._persist(run, findings=self._findings.get(run.id, []))

        try:
            if run.profile == SecurityProfile.QUICK:
                findings, tools_executed, tool_warnings = self._execute_quick_profile(
                    run_id=run.id,
                    target_path=run.target.repository_path,
                    timeout_seconds=run.options.timeout_seconds,
                )
            elif run.profile == SecurityProfile.STANDARD:
                findings, tools_executed, tool_warnings = self._execute_standard_profile(
                    run_id=run.id,
                    target_path=run.target.repository_path,
                    timeout_seconds=run.options.timeout_seconds,
                )
            else:
                findings, tools_executed, tool_warnings = self._execute_deep_profile(
                    run_id=run.id,
                    target_path=run.target.repository_path,
                    timeout_seconds=run.options.timeout_seconds,
                )
            if run.status == RunStatus.CANCELLED:
                run.metadata.tools_executed = tools_executed
                run.metadata.tool_warnings = tool_warnings
                run.touch()
                self._persist(run, findings=self._findings.get(run.id, []))
                return run
            # Append results from registered MCP security servers (non-fatal)
            mcp_findings = await self._run_mcp_servers(
                run_id=run.id,
                target_path=run.target.repository_path,
                tools_executed=tools_executed,
                tool_warnings=tool_warnings,
            )
            findings.extend(mcp_findings)
            findings = self._apply_dedup(findings)
            self._findings[run.id] = findings
            run.findings_count = len(findings)
            run.findings_summary = FindingsSummary.from_findings(findings)
            run.metadata.tools_executed = tools_executed
            run.metadata.tool_warnings = tool_warnings
            run.status = RunStatus.COMPLETED
            run.touch()
            run.completed_at = run.updated_at
            self._persist(run, findings)
        except subprocess.TimeoutExpired:
            run.status = RunStatus.TIMEOUT
            run.error_message = "Scan timed out while executing quick profile"
            run.touch()
            run.completed_at = run.updated_at
            self._persist(run, findings=self._findings.get(run.id, []))
        except ToolExecutionError as exc:
            run.status = RunStatus.FAILED
            run.error_message = str(exc)
            run.touch()
            run.completed_at = run.updated_at
            self._persist(run, findings=self._findings.get(run.id, []))
        return run

    def fetch_findings(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        min_severity: FindingSeverity | None = None,
    ) -> list[SecurityFinding]:
        """Return findings for a run with optional minimum severity filter."""
        run = self.get_run(run_id, tenant_id=tenant_id)
        findings = self._findings.get(run.id, [])
        if not findings and self._store is not None:
            findings = self._load_findings_for_run(run.id)
        if min_severity is None:
            return findings
        min_score = _SEVERITY_ORDER[min_severity]
        return [finding for finding in findings if _SEVERITY_ORDER[finding.severity] >= min_score]

    def cancel_run(self, run_id: str, *, tenant_id: str | None = None) -> SecurityRun:
        """Cancel a non-terminal run."""
        run = self.get_run(run_id, tenant_id=tenant_id)
        if run.status in _TERMINAL_STATES:
            raise RunStateError(f"Run {run.id} is already {run.status.value}")
        run.status = RunStatus.CANCELLED
        run.touch()
        run.completed_at = run.updated_at
        self._persist(run, findings=self._findings.get(run.id, []))
        return run

    def delete_run(self, run_id: str, *, tenant_id: str | None = None) -> None:
        """Delete run and associated findings."""
        run = self.get_run(run_id, tenant_id=tenant_id)
        del self._runs[run.id]
        self._findings.pop(run.id, None)
        if self._store is not None:
            self._store.delete_run(run.id)

    def add_findings(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
        findings: list[SecurityFinding],
    ) -> SecurityRun:
        """Append findings to an existing run and persist."""
        run = self.get_run(run_id, tenant_id=tenant_id)
        if not findings:
            self._persist(run, findings=self._findings.get(run.id, []))
            return run
        existing = list(self._findings.get(run.id, []))
        combined = existing + findings
        self._findings[run.id] = combined
        run.findings_count = len(combined)
        run.findings_summary = FindingsSummary.from_findings(combined)
        run.touch()
        self._persist(run, findings=combined)
        return run

    def sarif_export(
        self,
        run_id: str,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Export findings for a completed run as SARIF 2.1.0 JSON."""
        from agent33.component_security.sarif import SARIFConverter

        findings = self.fetch_findings(run_id, tenant_id=tenant_id)
        run = self.get_run(run_id, tenant_id=tenant_id)
        return SARIFConverter.findings_to_sarif(
            findings,
            tool_name=f"agent33-{run.profile.value}-scan",
        )

    def _execute_quick_profile(
        self,
        *,
        run_id: str,
        target_path: str,
        timeout_seconds: int,
    ) -> tuple[list[SecurityFinding], list[str], list[str]]:
        target = self._validate_target_path(target_path)

        normalized_target = str(target)
        bandit_raw = self._run_bandit(
            target_path=normalized_target, timeout_seconds=timeout_seconds
        )
        gitleaks_raw = self._run_gitleaks(
            target_path=normalized_target, timeout_seconds=timeout_seconds
        )
        findings = self._parse_bandit_findings(run_id=run_id, raw_output=bandit_raw)
        findings.extend(self._parse_gitleaks_findings(run_id=run_id, raw_output=gitleaks_raw))
        return findings, ["bandit", "gitleaks"], []

    def _execute_standard_profile(
        self,
        *,
        run_id: str,
        target_path: str,
        timeout_seconds: int,
    ) -> tuple[list[SecurityFinding], list[str], list[str]]:
        findings, tools_executed, tool_warnings = self._execute_quick_profile(
            run_id=run_id,
            target_path=target_path,
            timeout_seconds=timeout_seconds,
        )
        pip_audit_raw = self._run_optional_command(
            command=[sys.executable, "-m", "pip_audit", "-f", "json"],
            timeout_seconds=timeout_seconds,
            tool_name="pip-audit",
            warnings=tool_warnings,
        )
        tools_executed.append("pip-audit")
        if pip_audit_raw:
            findings.extend(
                self._parse_pip_audit_findings(
                    run_id=run_id,
                    raw_output=pip_audit_raw,
                )
            )
        return findings, tools_executed, tool_warnings

    def _execute_deep_profile(
        self,
        *,
        run_id: str,
        target_path: str,
        timeout_seconds: int,
    ) -> tuple[list[SecurityFinding], list[str], list[str]]:
        findings, tools_executed, tool_warnings = self._execute_standard_profile(
            run_id=run_id,
            target_path=target_path,
            timeout_seconds=timeout_seconds,
        )
        semgrep_raw = self._run_optional_command(
            command=["semgrep", "--json", target_path],
            timeout_seconds=timeout_seconds,
            tool_name="semgrep",
            warnings=tool_warnings,
        )
        tools_executed.append("semgrep")
        if semgrep_raw:
            findings.extend(self._parse_semgrep_findings(run_id=run_id, raw_output=semgrep_raw))
        return findings, tools_executed, tool_warnings

    async def _run_mcp_servers(
        self,
        *,
        run_id: str,
        target_path: str,
        tools_executed: list[str],
        tool_warnings: list[str],
    ) -> list[SecurityFinding]:
        """Call all registered MCP security servers and collect findings.

        Each server is invoked sequentially. Failures are logged and surfaced as
        a tool warning but never abort the overall scan run.
        """
        if self._mcp_scanner is None:
            return []
        servers = self._mcp_scanner.list_servers()
        if not servers:
            return []

        all_mcp_findings: list[SecurityFinding] = []
        for server in servers:
            try:
                findings = await self._mcp_scanner.scan(
                    server_name=server.name,
                    target=target_path,
                    run_id=run_id,
                )
                all_mcp_findings.extend(findings)
                tools_executed.append(f"mcp:{server.name}")
                logger.info(
                    "mcp_security_server_completed",
                    server=server.name,
                    findings=len(findings),
                )
            except Exception:
                warning = f"mcp:{server.name} scan failed; continuing without its findings"
                tool_warnings.append(warning)
                logger.warning(
                    "mcp_security_server_failed",
                    server=server.name,
                    exc_info=True,
                )
        return all_mcp_findings

    def _validate_target_path(self, target_path: str) -> Path:
        if "\x00" in target_path:
            raise ToolExecutionError("Scan target path cannot contain null bytes")
        target = Path(target_path)
        if not target.exists():
            raise ToolExecutionError(f"Scan target does not exist: {target_path}")
        resolved = target.resolve()
        if not self._allowed_roots:
            return resolved

        for allowed_root in self._allowed_roots:
            try:
                resolved.relative_to(allowed_root)
                return resolved
            except ValueError:
                continue

        allowed = ", ".join(str(root) for root in self._allowed_roots)
        raise ToolExecutionError(
            f"Scan target '{resolved}' is outside allowed directories: {allowed}"
        )

    def _run_bandit(self, *, target_path: str, timeout_seconds: int) -> str:
        command = [sys.executable, "-m", "bandit", "-r", target_path, "-f", "json", "-q"]
        try:
            result = self._command_runner(command, timeout_seconds)
        except FileNotFoundError as exc:
            raise ToolExecutionError(
                "Bandit is not installed in the execution environment"
            ) from exc
        if result.returncode not in {0, 1}:
            error_text = (
                result.stderr.strip() or result.stdout.strip() or "Bandit execution failed"
            )
            raise ToolExecutionError(error_text)
        return result.stdout

    def _run_gitleaks(self, *, target_path: str, timeout_seconds: int) -> str:
        command = [
            "gitleaks",
            "detect",
            "--source",
            target_path,
            "--report-format",
            "json",
            "--report-path",
            "-",
            "--no-banner",
            "--exit-code",
            "0",
        ]
        try:
            result = self._command_runner(command, timeout_seconds)
        except FileNotFoundError as exc:
            raise ToolExecutionError(
                "gitleaks is not installed in the execution environment"
            ) from exc
        if result.returncode != 0:
            error_text = (
                result.stderr.strip() or result.stdout.strip() or "gitleaks execution failed"
            )
            raise ToolExecutionError(error_text)
        return result.stdout

    def _run_command(
        self, command: list[str], timeout_seconds: int
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )

    def _run_optional_command(
        self,
        *,
        command: list[str],
        timeout_seconds: int,
        tool_name: str,
        warnings: list[str],
    ) -> str | None:
        try:
            result = self._command_runner(command, timeout_seconds)
        except FileNotFoundError:
            warning = f"{tool_name} is not installed; continuing without {tool_name} findings"
            warnings.append(warning)
            logger.warning("component_security_optional_tool_missing", tool=tool_name)
            return None

        if result.returncode != 0:
            warning = (
                f"{tool_name} execution returned non-zero exit code {result.returncode}; "
                f"continuing without {tool_name} findings"
            )
            warnings.append(warning)
            logger.warning(
                "component_security_optional_tool_failed",
                tool=tool_name,
                return_code=result.returncode,
            )
            return None
        return result.stdout

    def _parse_bandit_findings(self, *, run_id: str, raw_output: str) -> list[SecurityFinding]:
        if not raw_output.strip():
            return []
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("Bandit output was not valid JSON") from exc

        raw_findings = payload.get("results", [])
        findings: list[SecurityFinding] = []
        for issue in raw_findings:
            findings.append(
                SecurityFinding(
                    run_id=run_id,
                    severity=self._map_bandit_severity(issue.get("issue_severity", "")),
                    category=self._map_bandit_category(issue.get("issue_text", "")),
                    title=issue.get("issue_text", "Bandit finding"),
                    description=issue.get("issue_text", "Bandit finding"),
                    tool="bandit",
                    file_path=issue.get("filename", ""),
                    line_number=issue.get("line_number"),
                    remediation=issue.get("more_info", ""),
                    cwe_id=str(issue.get("issue_cwe", {}).get("id") or ""),
                )
            )
        return findings

    def _parse_gitleaks_findings(self, *, run_id: str, raw_output: str) -> list[SecurityFinding]:
        if not raw_output.strip():
            return []
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("gitleaks output was not valid JSON") from exc
        if not isinstance(payload, list):
            raise ToolExecutionError("gitleaks output must be a JSON array")

        findings: list[SecurityFinding] = []
        for leak in payload:
            findings.append(
                SecurityFinding(
                    run_id=run_id,
                    severity=FindingSeverity.HIGH,
                    category=FindingCategory.SECRETS_EXPOSURE,
                    title=leak.get("Description", leak.get("RuleID", "gitleaks finding")),
                    description=leak.get("Description", "Potential secret exposure"),
                    tool="gitleaks",
                    file_path=leak.get("File", ""),
                    line_number=leak.get("StartLine"),
                    remediation="Rotate exposed secret and remove it from repository history",
                )
            )
        return findings

    def _parse_pip_audit_findings(self, *, run_id: str, raw_output: str) -> list[SecurityFinding]:
        if not raw_output.strip():
            return []
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("pip-audit output was not valid JSON") from exc

        dependencies = payload.get("dependencies", [])
        findings: list[SecurityFinding] = []
        for dependency in dependencies:
            for vulnerability in dependency.get("vulns", []):
                vuln_id = vulnerability.get("id", "")
                description = (
                    vulnerability.get("description") or vuln_id or "Dependency vulnerability"
                )
                findings.append(
                    SecurityFinding(
                        run_id=run_id,
                        severity=FindingSeverity.HIGH,
                        category=FindingCategory.DEPENDENCY_VULNERABILITY,
                        title=f"{dependency.get('name', 'dependency')} {vuln_id}".strip(),
                        description=description,
                        tool="pip-audit",
                        remediation=", ".join(vulnerability.get("fix_versions", [])),
                        cwe_id=vuln_id,
                    )
                )
        return findings

    def _parse_semgrep_findings(self, *, run_id: str, raw_output: str) -> list[SecurityFinding]:
        if not raw_output.strip():
            return []
        try:
            payload = json.loads(raw_output)
        except json.JSONDecodeError as exc:
            raise ToolExecutionError("semgrep output was not valid JSON") from exc

        results = payload.get("results", [])
        findings: list[SecurityFinding] = []
        for result in results:
            extra = result.get("extra", {})
            check_id = result.get("check_id", "")
            severity = self._map_semgrep_severity(str(extra.get("severity", "")))
            message = str(extra.get("message") or check_id or "Semgrep finding")
            findings.append(
                SecurityFinding(
                    run_id=run_id,
                    severity=severity,
                    category=self._map_semgrep_category(check_id),
                    title=message,
                    description=message,
                    tool="semgrep",
                    file_path=str(result.get("path", "")),
                    line_number=result.get("start", {}).get("line"),
                    remediation="Review and remediate rule violation in source code",
                )
            )
        return findings

    @staticmethod
    def _map_bandit_severity(raw_severity: str) -> FindingSeverity:
        normalized = raw_severity.lower()
        if normalized == "high":
            return FindingSeverity.HIGH
        if normalized == "medium":
            return FindingSeverity.MEDIUM
        if normalized == "low":
            return FindingSeverity.LOW
        return FindingSeverity.INFO

    @staticmethod
    def _map_bandit_category(issue_text: str) -> FindingCategory:
        lowered = issue_text.lower()
        if "inject" in lowered or "exec" in lowered or "subprocess" in lowered:
            return FindingCategory.INJECTION_RISK
        if "auth" in lowered:
            return FindingCategory.AUTHENTICATION_WEAKNESS
        return FindingCategory.CODE_QUALITY

    @staticmethod
    def _map_semgrep_severity(raw_severity: str) -> FindingSeverity:
        normalized = raw_severity.lower()
        if normalized in {"error", "high"}:
            return FindingSeverity.HIGH
        if normalized in {"warning", "medium"}:
            return FindingSeverity.MEDIUM
        if normalized in {"info", "low"}:
            return FindingSeverity.LOW
        return FindingSeverity.INFO

    @staticmethod
    def _map_semgrep_category(check_id: str) -> FindingCategory:
        lowered = check_id.lower()
        if "authz" in lowered or "authorization" in lowered:
            return FindingCategory.AUTHORIZATION_BYPASS
        if "auth" in lowered:
            return FindingCategory.AUTHENTICATION_WEAKNESS
        if "crypto" in lowered:
            return FindingCategory.CRYPTOGRAPHY_WEAKNESS
        if "config" in lowered:
            return FindingCategory.CONFIGURATION_ISSUE
        if "inject" in lowered:
            return FindingCategory.INJECTION_RISK
        return FindingCategory.CODE_QUALITY

    # ------------------------------------------------------------------
    # Persistence & dedup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_dedup(findings: list[SecurityFinding]) -> list[SecurityFinding]:
        """Deduplicate findings by fingerprint."""
        from agent33.component_security.dedup import deduplicate_findings

        return deduplicate_findings(findings)

    def _load_persisted_state(self) -> None:
        """Load persisted runs and findings into memory cache."""
        self._refresh_from_store()

    def _refresh_from_store(self) -> None:
        """Refresh in-memory cache from persistent storage."""
        if self._store is None:
            return
        try:
            persisted_rows = self._store.list_runs(limit=10000)
        except Exception:
            logger.exception("security_scan_store_list_failed")
            return
        refreshed_runs: dict[str, SecurityRun] = {}
        refreshed_findings: dict[str, list[SecurityFinding]] = {}
        for row in persisted_rows:
            run = self._run_from_store_row(row)
            if run is None:
                continue
            refreshed_runs[run.id] = run
            try:
                refreshed_findings[run.id] = self._load_findings_for_run(run.id)
            except Exception:
                logger.exception(
                    "security_scan_store_findings_load_failed",
                    run_id=run.id,
                )
                refreshed_findings[run.id] = []
        self._runs = refreshed_runs
        self._findings = refreshed_findings

    def _persist(self, run: SecurityRun, findings: list[SecurityFinding]) -> None:
        """Persist run state and findings when a store is configured."""
        if self._store is None:
            return
        try:
            self._store.save_run(run)
            self._store.replace_findings(run.id, findings)
        except Exception:
            logger.exception("security_scan_persist_failed", run_id=run.id)

    def _load_run_from_store(self, run_id: str) -> SecurityRun | None:
        """Load a run by ID from persistent storage."""
        if self._store is None:
            return None
        row = self._store.get_run(run_id)
        if row is None:
            self._runs.pop(run_id, None)
            self._findings.pop(run_id, None)
            return None
        run = self._run_from_store_row(row)
        if run is None:
            self._runs.pop(run_id, None)
            self._findings.pop(run_id, None)
            return None
        self._runs[run.id] = run
        try:
            self._findings[run.id] = self._load_findings_for_run(run.id)
        except Exception:
            logger.exception("security_scan_store_findings_load_failed", run_id=run.id)
            self._findings[run.id] = []
        return run

    def _load_findings_for_run(self, run_id: str) -> list[SecurityFinding]:
        """Load findings for a run from persistent storage."""
        if self._store is None:
            return []
        rows = self._store.get_findings(run_id)
        findings: list[SecurityFinding] = []
        for row in rows:
            finding = self._finding_from_store_row(row)
            if finding is not None:
                findings.append(finding)
        self._findings[run_id] = findings
        return findings

    def _run_from_store_row(self, row: dict[str, object]) -> SecurityRun | None:
        """Convert a stored run row to SecurityRun."""
        payload = row.get("payload")
        if isinstance(payload, dict) and payload:
            try:
                return SecurityRun.model_validate(payload)
            except Exception:
                logger.warning(
                    "security_scan_store_run_payload_invalid",
                    run_id=row.get("id"),
                )
        try:
            status = RunStatus(str(row["status"]))
            profile = SecurityProfile(str(row["profile"]))
        except (KeyError, ValueError):
            return None
        tools_used = row.get("tools_used")
        if not isinstance(tools_used, list):
            tools_used = []
        summary_payload = row.get("summary")
        if not isinstance(summary_payload, dict):
            summary_payload = {}
        findings_summary = FindingsSummary.model_validate(summary_payload)
        target_path = row.get("target_path")
        created_at = row.get("created_at")
        updated_at = row.get("updated_at")
        started_at = row.get("started_at")
        completed_at = row.get("completed_at")
        return SecurityRun(
            id=str(row["id"]),
            tenant_id=str(row.get("tenant_id", "")),
            profile=profile,
            status=status,
            target=ScanTarget(repository_path=str(target_path)),
            findings_count=findings_summary.total,
            findings_summary=findings_summary,
            created_at=created_at if isinstance(created_at, datetime) else datetime.now(UTC),
            updated_at=(
                updated_at
                if isinstance(updated_at, datetime)
                else created_at
                if isinstance(created_at, datetime)
                else datetime.now(UTC)
            ),
            started_at=started_at if isinstance(started_at, datetime) else None,
            completed_at=completed_at if isinstance(completed_at, datetime) else None,
        )

    @staticmethod
    def _finding_from_store_row(row: dict[str, object]) -> SecurityFinding | None:
        """Convert a stored finding row to SecurityFinding."""
        payload = row.get("payload")
        if isinstance(payload, dict) and payload:
            try:
                return SecurityFinding.model_validate(payload)
            except Exception:
                logger.warning(
                    "security_scan_store_finding_payload_invalid",
                    finding_id=row.get("id"),
                )
        try:
            severity = FindingSeverity(str(row["severity"]))
            category = FindingCategory(str(row["category"]))
        except (KeyError, ValueError):
            return None
        return SecurityFinding(
            id=str(row.get("id", "")),
            run_id=str(row["run_id"]),
            severity=severity,
            category=category,
            title=str(row.get("title", "")),
            description=str(row.get("description", "")),
            tool=str(row.get("tool", "")),
            file_path=str(row.get("file_path", "")),
            line_number=row.get("line_number"),
            remediation=str(row.get("recommendation", "")),
            cwe_id=str(row.get("cwe_id", "")),
            created_at=(
                row.get("created_at")
                if isinstance(row.get("created_at"), datetime)
                else datetime.now(UTC)
            ),
            cvss_score=row.get("cvss_score") if "cvss_score" in row else None,
        )

    def _apply_store_retention(self) -> None:
        """Apply retention policy before hydrating persisted state."""
        if self._store is None or self._store_retention_days is None:
            return
        if self._store_retention_days <= 0:
            return
        try:
            self._store.cleanup_expired_runs(retention_days=self._store_retention_days)
        except Exception:
            logger.exception(
                "security_scan_store_retention_failed",
                retention_days=self._store_retention_days,
            )
