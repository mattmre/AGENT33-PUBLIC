"""SARIF 2.1.0 bidirectional converter for component security findings."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent33.component_security.models import (
    FindingCategory,
    FindingSeverity,
    SecurityFinding,
)

# SARIF 2.1.0 schema URI
SARIF_SCHEMA = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec"
    "/main/sarif-2.1/schema/sarif-schema-2.1.0.json"
)
SARIF_VERSION = "2.1.0"

# Severity mapping: AGENT-33 → SARIF level
_SEVERITY_TO_LEVEL: dict[FindingSeverity, str] = {
    FindingSeverity.CRITICAL: "error",
    FindingSeverity.HIGH: "error",
    FindingSeverity.MEDIUM: "warning",
    FindingSeverity.LOW: "note",
    FindingSeverity.INFO: "note",
}

# Reverse mapping: SARIF level → default AGENT-33 severity
_LEVEL_TO_SEVERITY: dict[str, FindingSeverity] = {
    "error": FindingSeverity.HIGH,
    "warning": FindingSeverity.MEDIUM,
    "note": FindingSeverity.LOW,
    "none": FindingSeverity.INFO,
}

# Category → SARIF ruleId prefix
_CATEGORY_RULE_PREFIX: dict[FindingCategory, str] = {
    FindingCategory.DEPENDENCY_VULNERABILITY: "DEP",
    FindingCategory.SECRETS_EXPOSURE: "SEC",
    FindingCategory.INJECTION_RISK: "INJ",
    FindingCategory.CODE_QUALITY: "CQ",
    FindingCategory.AUTHENTICATION_WEAKNESS: "AUTH",
    FindingCategory.AUTHORIZATION_BYPASS: "AUTHZ",
    FindingCategory.CRYPTOGRAPHY_WEAKNESS: "CRYPTO",
    FindingCategory.CONFIGURATION_ISSUE: "CFG",
    FindingCategory.PROMPT_INJECTION: "PI",
    FindingCategory.TOOL_POISONING: "TP",
    FindingCategory.SUPPLY_CHAIN: "SC",
    FindingCategory.MODEL_SECURITY: "MS",
}

# Reverse: ruleId prefix → category
_RULE_PREFIX_TO_CATEGORY: dict[str, FindingCategory] = {
    v: k for k, v in _CATEGORY_RULE_PREFIX.items()
}


class SARIFConverter:
    """Bidirectional converter between SecurityFinding and SARIF 2.1.0."""

    @staticmethod
    def findings_to_sarif(
        findings: list[SecurityFinding],
        tool_name: str = "agent33-security-scan",
        tool_version: str = "1.0.0",
    ) -> dict[str, Any]:
        """Convert findings to SARIF 2.1.0 JSON structure."""
        rules: dict[str, dict[str, Any]] = {}
        results: list[dict[str, Any]] = []

        for finding in findings:
            prefix = _CATEGORY_RULE_PREFIX.get(finding.category, "GEN")
            rule_id = f"{prefix}/{finding.tool}/{finding.cwe_id or finding.id}"

            if rule_id not in rules:
                rules[rule_id] = {
                    "id": rule_id,
                    "shortDescription": {"text": finding.title},
                    "helpUri": finding.remediation or "",
                    "properties": {"category": finding.category.value},
                }

            sarif_result: dict[str, Any] = {
                "ruleId": rule_id,
                "level": _SEVERITY_TO_LEVEL.get(finding.severity, "note"),
                "message": {"text": finding.description},
                "properties": {
                    "finding_id": finding.id,
                    "severity": finding.severity.value,
                    "category": finding.category.value,
                    "tool": finding.tool,
                },
            }

            if finding.file_path:
                location: dict[str, Any] = {
                    "physicalLocation": {
                        "artifactLocation": {"uri": finding.file_path},
                    }
                }
                if finding.line_number is not None:
                    location["physicalLocation"]["region"] = {"startLine": finding.line_number}
                sarif_result["locations"] = [location]

            if finding.remediation:
                sarif_result["fixes"] = [{"description": {"text": finding.remediation}}]

            results.append(sarif_result)

        return {
            "$schema": SARIF_SCHEMA,
            "version": SARIF_VERSION,
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": tool_name,
                            "version": tool_version,
                            "rules": list(rules.values()),
                        }
                    },
                    "results": results,
                    "invocations": [
                        {
                            "executionSuccessful": True,
                            "endTimeUtc": datetime.now(UTC).isoformat(),
                        }
                    ],
                }
            ],
        }

    @staticmethod
    def sarif_to_findings(
        sarif: dict[str, Any],
        run_id: str,
    ) -> list[SecurityFinding]:
        """Ingest external SARIF 2.1.0 JSON and convert to SecurityFindings."""
        findings: list[SecurityFinding] = []
        runs = sarif.get("runs", [])

        for run in runs:
            tool_name = run.get("tool", {}).get("driver", {}).get("name", "unknown")
            rules_by_id: dict[str, dict[str, Any]] = {}
            for rule in run.get("tool", {}).get("driver", {}).get("rules", []):
                rules_by_id[rule.get("id", "")] = rule

            for result in run.get("results", []):
                rule_id = result.get("ruleId", "")
                level = result.get("level", "note")
                message = result.get("message", {}).get("text", "")

                # Determine severity from properties or level
                props = result.get("properties", {})
                if "severity" in props:
                    try:
                        severity = FindingSeverity(props["severity"])
                    except ValueError:
                        severity = _LEVEL_TO_SEVERITY.get(level, FindingSeverity.INFO)
                else:
                    severity = _LEVEL_TO_SEVERITY.get(level, FindingSeverity.INFO)

                # Determine category from properties or rule prefix
                if "category" in props:
                    try:
                        category = FindingCategory(props["category"])
                    except ValueError:
                        category = _guess_category_from_rule(rule_id)
                else:
                    category = _guess_category_from_rule(rule_id)

                # Extract file location
                file_path = ""
                line_number = None
                locations = result.get("locations", [])
                if locations:
                    phys = locations[0].get("physicalLocation", {})
                    file_path = phys.get("artifactLocation", {}).get("uri", "")
                    region = phys.get("region", {})
                    line_number = region.get("startLine")

                # Extract remediation
                remediation = ""
                fixes = result.get("fixes", [])
                if fixes:
                    remediation = fixes[0].get("description", {}).get("text", "")

                # Extract CWE from rule ID
                cwe_id = ""
                if "/" in rule_id:
                    parts = rule_id.split("/")
                    if len(parts) >= 3:
                        cwe_id = parts[2]

                tool = props.get("tool", tool_name)

                findings.append(
                    SecurityFinding(
                        run_id=run_id,
                        severity=severity,
                        category=category,
                        title=rule_by_id_title(rules_by_id, rule_id, message),
                        description=message,
                        tool=tool,
                        file_path=file_path,
                        line_number=line_number,
                        remediation=remediation,
                        cwe_id=cwe_id,
                    )
                )

        return findings


def rule_by_id_title(rules_by_id: dict[str, dict[str, Any]], rule_id: str, fallback: str) -> str:
    """Extract title from rule, falling back to message."""
    rule = rules_by_id.get(rule_id, {})
    result: str = rule.get("shortDescription", {}).get("text", fallback)
    return result


def _guess_category_from_rule(rule_id: str) -> FindingCategory:
    """Guess category from SARIF rule ID prefix."""
    if "/" in rule_id:
        prefix = rule_id.split("/")[0]
        if prefix in _RULE_PREFIX_TO_CATEGORY:
            return _RULE_PREFIX_TO_CATEGORY[prefix]
    return FindingCategory.CODE_QUALITY
