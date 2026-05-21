"""Tests for SARIF 2.1.0 bidirectional converter."""

from __future__ import annotations

from agent33.component_security.models import (
    FindingCategory,
    FindingSeverity,
    SecurityFinding,
)
from agent33.component_security.sarif import (
    SARIF_SCHEMA,
    SARIF_VERSION,
    SARIFConverter,
)


def _make_finding(
    *,
    severity: FindingSeverity = FindingSeverity.HIGH,
    category: FindingCategory = FindingCategory.CODE_QUALITY,
    tool: str = "bandit",
    file_path: str = "app.py",
    line_number: int | None = 10,
    cwe_id: str = "CWE-78",
    remediation: str = "Fix the issue",
) -> SecurityFinding:
    return SecurityFinding(
        run_id="secrun-test",
        severity=severity,
        category=category,
        title=f"Test finding ({severity.value})",
        description=f"Description for {severity.value} finding",
        tool=tool,
        file_path=file_path,
        line_number=line_number,
        cwe_id=cwe_id,
        remediation=remediation,
    )


class TestFindingsToSarif:
    def test_basic_structure(self) -> None:
        findings = [_make_finding()]
        sarif = SARIFConverter.findings_to_sarif(findings)

        assert sarif["$schema"] == SARIF_SCHEMA
        assert sarif["version"] == SARIF_VERSION
        assert len(sarif["runs"]) == 1

        run = sarif["runs"][0]
        assert run["tool"]["driver"]["name"] == "agent33-security-scan"
        assert len(run["results"]) == 1
        assert len(run["tool"]["driver"]["rules"]) == 1

    def test_severity_mapping(self) -> None:
        findings = [
            _make_finding(severity=FindingSeverity.CRITICAL),
            _make_finding(severity=FindingSeverity.HIGH),
            _make_finding(severity=FindingSeverity.MEDIUM),
            _make_finding(severity=FindingSeverity.LOW),
            _make_finding(severity=FindingSeverity.INFO),
        ]
        sarif = SARIFConverter.findings_to_sarif(findings)
        levels = [r["level"] for r in sarif["runs"][0]["results"]]
        assert levels == ["error", "error", "warning", "note", "note"]

    def test_location_included(self) -> None:
        finding = _make_finding(file_path="src/main.py", line_number=42)
        sarif = SARIFConverter.findings_to_sarif([finding])
        result = sarif["runs"][0]["results"][0]

        assert "locations" in result
        loc = result["locations"][0]["physicalLocation"]
        assert loc["artifactLocation"]["uri"] == "src/main.py"
        assert loc["region"]["startLine"] == 42

    def test_no_location_when_no_file(self) -> None:
        finding = _make_finding(file_path="", line_number=None)
        sarif = SARIFConverter.findings_to_sarif([finding])
        result = sarif["runs"][0]["results"][0]
        assert "locations" not in result

    def test_empty_findings(self) -> None:
        sarif = SARIFConverter.findings_to_sarif([])
        assert sarif["runs"][0]["results"] == []
        assert sarif["runs"][0]["tool"]["driver"]["rules"] == []

    def test_remediation_in_fixes(self) -> None:
        finding = _make_finding(remediation="Upgrade to v2.0")
        sarif = SARIFConverter.findings_to_sarif([finding])
        result = sarif["runs"][0]["results"][0]
        assert result["fixes"][0]["description"]["text"] == "Upgrade to v2.0"

    def test_no_fixes_when_no_remediation(self) -> None:
        finding = _make_finding(remediation="")
        sarif = SARIFConverter.findings_to_sarif([finding])
        result = sarif["runs"][0]["results"][0]
        assert "fixes" not in result

    def test_custom_tool_name(self) -> None:
        sarif = SARIFConverter.findings_to_sarif(
            [_make_finding()],
            tool_name="my-scanner",
            tool_version="2.5.0",
        )
        driver = sarif["runs"][0]["tool"]["driver"]
        assert driver["name"] == "my-scanner"
        assert driver["version"] == "2.5.0"

    def test_category_in_rule_prefix(self) -> None:
        finding = _make_finding(category=FindingCategory.INJECTION_RISK)
        sarif = SARIFConverter.findings_to_sarif([finding])
        rule = sarif["runs"][0]["tool"]["driver"]["rules"][0]
        assert rule["id"].startswith("INJ/")

    def test_all_severity_levels_produce_valid_sarif(self) -> None:
        for sev in FindingSeverity:
            finding = _make_finding(severity=sev)
            sarif = SARIFConverter.findings_to_sarif([finding])
            result = sarif["runs"][0]["results"][0]
            assert result["level"] in {"error", "warning", "note"}


class TestSarifToFindings:
    def test_basic_round_trip(self) -> None:
        original = [
            _make_finding(
                severity=FindingSeverity.HIGH,
                category=FindingCategory.INJECTION_RISK,
            ),
            _make_finding(
                severity=FindingSeverity.LOW,
                category=FindingCategory.SECRETS_EXPOSURE,
                tool="gitleaks",
                file_path="config.py",
                line_number=5,
            ),
        ]
        sarif = SARIFConverter.findings_to_sarif(original)
        restored = SARIFConverter.sarif_to_findings(sarif, run_id="secrun-rt")

        assert len(restored) == len(original)
        for orig, rest in zip(original, restored, strict=True):
            assert rest.severity == orig.severity
            assert rest.category == orig.category
            assert rest.tool == orig.tool
            assert rest.file_path == orig.file_path
            assert rest.line_number == orig.line_number
            assert rest.run_id == "secrun-rt"

    def test_ingest_external_sarif(self) -> None:
        external_sarif = {
            "$schema": SARIF_SCHEMA,
            "version": SARIF_VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "external-scanner",
                            "version": "1.0.0",
                            "rules": [
                                {
                                    "id": "EXT-001",
                                    "shortDescription": {"text": "External finding"},
                                }
                            ],
                        }
                    },
                    "results": [
                        {
                            "ruleId": "EXT-001",
                            "level": "error",
                            "message": {"text": "Found a vulnerability"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "test.py"},
                                        "region": {"startLine": 100},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        findings = SARIFConverter.sarif_to_findings(external_sarif, run_id="secrun-ext")
        assert len(findings) == 1
        finding = findings[0]
        assert finding.severity == FindingSeverity.HIGH  # error → HIGH
        assert finding.file_path == "test.py"
        assert finding.line_number == 100
        assert finding.tool == "external-scanner"
        assert finding.run_id == "secrun-ext"

    def test_empty_sarif(self) -> None:
        empty = {"version": SARIF_VERSION, "runs": []}
        findings = SARIFConverter.sarif_to_findings(empty, run_id="secrun-empty")
        assert findings == []

    def test_missing_runs(self) -> None:
        findings = SARIFConverter.sarif_to_findings({}, run_id="secrun-none")
        assert findings == []

    def test_multiple_runs(self) -> None:
        sarif = {
            "version": SARIF_VERSION,
            "runs": [
                {
                    "tool": {"driver": {"name": "tool-a", "rules": []}},
                    "results": [
                        {
                            "ruleId": "A-1",
                            "level": "warning",
                            "message": {"text": "a"},
                        },
                    ],
                },
                {
                    "tool": {"driver": {"name": "tool-b", "rules": []}},
                    "results": [
                        {
                            "ruleId": "B-1",
                            "level": "error",
                            "message": {"text": "b"},
                        },
                    ],
                },
            ],
        }
        findings = SARIFConverter.sarif_to_findings(sarif, run_id="secrun-multi")
        assert len(findings) == 2
        assert findings[0].tool == "tool-a"
        assert findings[1].tool == "tool-b"


class TestClaudeSecurityAdapter:
    def test_ingest_sarif(self) -> None:
        from agent33.component_security.claude_security import (
            ClaudeSecurityAdapter,
        )

        adapter = ClaudeSecurityAdapter()
        sarif = SARIFConverter.findings_to_sarif(
            [_make_finding()], tool_name="claude-code-security"
        )
        findings = adapter.ingest_sarif(sarif, run_id="secrun-claude")
        assert len(findings) == 1
        assert findings[0].run_id == "secrun-claude"

    def test_is_available_returns_false_locally(self, monkeypatch) -> None:
        from agent33.component_security.claude_security import (
            ClaudeSecurityAdapter,
        )

        monkeypatch.delenv("CLAUDE_SECURITY_SARIF_PATH", raising=False)
        assert ClaudeSecurityAdapter.is_available() is False

    def test_is_available_detects_configured_sarif(self, tmp_path, monkeypatch) -> None:
        from agent33.component_security.claude_security import (
            ClaudeSecurityAdapter,
        )

        sarif_path = tmp_path / "claude.sarif"
        sarif_path.write_text("{}", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_SECURITY_SARIF_PATH", str(sarif_path))

        assert ClaudeSecurityAdapter.is_available() is True


class TestSarifRouteIntegration:
    def test_sarif_endpoint_returns_sarif(self) -> None:
        from fastapi.testclient import TestClient

        from agent33.api.routes import component_security
        from agent33.main import app
        from agent33.security.auth import create_access_token

        component_security._reset_service()
        service = component_security.get_component_security_service()
        app.state.security_scan_service = service
        service._runs.clear()
        service._findings.clear()
        service._command_runner = lambda cmd, t: __import__("subprocess").CompletedProcess(
            args=[], returncode=0, stdout='{"results": []}', stderr=""
        )
        service._allowed_roots = []

        token = create_access_token(
            "sarif-test",
            scopes=["component-security:read", "component-security:write"],
        )
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        # Create a completed run
        create_resp = client.post(
            "/v1/component-security/runs",
            json={
                "target": {"repository_path": "."},
                "profile": "quick",
                "execute_now": True,
            },
        )
        run_id = create_resp.json()["id"]

        # SARIF export (empty findings for pending run)
        sarif_resp = client.get(f"/v1/component-security/runs/{run_id}/sarif")
        assert sarif_resp.status_code == 200
        sarif = sarif_resp.json()
        assert sarif["version"] == SARIF_VERSION
        assert "$schema" in sarif
        assert len(sarif["runs"]) == 1

        # Clean up
        service._runs.clear()
        service._findings.clear()

    def test_sarif_endpoint_404_for_missing_run(self) -> None:
        from fastapi.testclient import TestClient

        from agent33.api.routes import component_security
        from agent33.main import app
        from agent33.security.auth import create_access_token

        component_security._reset_service()
        service = component_security.get_component_security_service()
        app.state.security_scan_service = service
        service._runs.clear()
        service._findings.clear()

        token = create_access_token(
            "sarif-test",
            scopes=["component-security:read"],
        )
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        resp = client.get("/v1/component-security/runs/secrun-nonexistent/sarif")
        assert resp.status_code == 404

        service._runs.clear()
        service._findings.clear()
