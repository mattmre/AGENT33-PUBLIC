"""Validate cross-references between operator documentation files.

Ensures that links between runbook, incident playbooks, scaling architecture,
SLO docs, and monitoring assets are all valid and bidirectional.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OPERATORS_DIR = _REPO_ROOT / "docs" / "operators"
_MONITORING_README = _REPO_ROOT / "deploy" / "monitoring" / "README.md"

# All operator docs we validate.
_OPERATOR_DOCS: dict[str, Path] = {
    "runbook": _OPERATORS_DIR / "production-deployment-runbook.md",
    "incident": _OPERATORS_DIR / "incident-response-playbooks.md",
    "scaling": _OPERATORS_DIR / "horizontal-scaling-architecture.md",
    "slo": _OPERATORS_DIR / "service-level-objectives.md",
    "connector_boundary": _OPERATORS_DIR / "connector-boundary-runbook.md",
    "pricing_effort": _OPERATORS_DIR / "pricing-and-effort-runbook.md",
    "voice": _OPERATORS_DIR / "voice-daemon-runbook.md",
    "verification": _OPERATORS_DIR / "operator-verification-runbook.md",
    "process_registry": _OPERATORS_DIR / "process-registry-runbook.md",
}

# Regex to extract markdown links: [text](target)
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

# Regex to extract headings from markdown (## Heading text)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _heading_to_anchor(heading: str) -> str:
    """Convert a markdown heading to a GitHub-style anchor slug.

    GitHub rules: lowercase, strip punctuation except hyphens, collapse spaces
    to hyphens, strip backticks.
    """
    slug = heading.lower()
    # Remove backticks
    slug = slug.replace("`", "")
    # Replace spaces and underscores with hyphens
    slug = re.sub(r"[\s_]+", "-", slug)
    # Strip characters that are not alphanumeric, hyphens, or forward slashes
    slug = re.sub(r"[^\w\-/]", "", slug)
    # Collapse consecutive hyphens
    slug = re.sub(r"-{2,}", "-", slug)
    # Strip leading/trailing hyphens
    slug = slug.strip("-")
    return slug


def _extract_links(content: str) -> list[tuple[str, str]]:
    """Return (display_text, target) for every markdown link in content."""
    return _LINK_RE.findall(content)


def _extract_headings(content: str) -> set[str]:
    """Return the set of anchor slugs for all headings in content."""
    anchors: set[str] = set()
    for match in _HEADING_RE.finditer(content):
        raw = match.group(2).strip()
        anchors.add(_heading_to_anchor(raw))
    return anchors


def _resolve_relative_path(source: Path, target: str) -> Path:
    """Resolve a relative link target from the source file's directory."""
    return (source.parent / target).resolve()


# ---- Test: all markdown links in operator docs resolve to real files ----


class TestOperatorDocLinksResolve:
    """Every markdown link in an operator doc must point to a real file."""

    def test_runbook_links_resolve(self) -> None:
        self._check_links(_OPERATOR_DOCS["runbook"])

    def test_incident_links_resolve(self) -> None:
        self._check_links(_OPERATOR_DOCS["incident"])

    def test_scaling_links_resolve(self) -> None:
        self._check_links(_OPERATOR_DOCS["scaling"])

    def test_slo_links_resolve(self) -> None:
        self._check_links(_OPERATOR_DOCS["slo"])

    def test_pricing_effort_links_resolve(self) -> None:
        self._check_links(_OPERATOR_DOCS["pricing_effort"])

    def test_voice_links_resolve(self) -> None:
        self._check_links(_OPERATOR_DOCS["voice"])

    def test_verification_links_resolve(self) -> None:
        self._check_links(_OPERATOR_DOCS["verification"])

    def test_process_registry_links_resolve(self) -> None:
        self._check_links(_OPERATOR_DOCS["process_registry"])

    @staticmethod
    def _check_links(doc_path: Path) -> None:
        content = doc_path.read_text(encoding="utf-8")
        links = _extract_links(content)
        broken: list[str] = []
        for _text, target in links:
            # Skip external URLs
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            # Split off any anchor fragment
            file_part = target.split("#")[0]
            if not file_part:
                # Pure anchor link within the same doc -- validated separately
                continue
            resolved = _resolve_relative_path(doc_path, file_part)
            if not resolved.exists():
                broken.append(f"  {target} -> {resolved}")
        assert not broken, f"Broken file links in {doc_path.name}:\n" + "\n".join(broken)


# ---- Test: section anchor references match real headings ----


class TestOperatorDocAnchors:
    """If a link contains a #fragment, it must match a heading in the target."""

    def test_runbook_anchors(self) -> None:
        self._check_anchors(_OPERATOR_DOCS["runbook"])

    def test_incident_anchors(self) -> None:
        self._check_anchors(_OPERATOR_DOCS["incident"])

    def test_scaling_anchors(self) -> None:
        self._check_anchors(_OPERATOR_DOCS["scaling"])

    def test_slo_anchors(self) -> None:
        self._check_anchors(_OPERATOR_DOCS["slo"])

    def test_connector_boundary_anchors(self) -> None:
        self._check_anchors(_OPERATOR_DOCS["connector_boundary"])

    def test_pricing_effort_anchors(self) -> None:
        self._check_anchors(_OPERATOR_DOCS["pricing_effort"])

    def test_verification_anchors(self) -> None:
        self._check_anchors(_OPERATOR_DOCS["verification"])

    def test_process_registry_anchors(self) -> None:
        self._check_anchors(_OPERATOR_DOCS["process_registry"])

    @staticmethod
    def _check_anchors(doc_path: Path) -> None:
        content = doc_path.read_text(encoding="utf-8")
        links = _extract_links(content)
        broken: list[str] = []
        for _text, target in links:
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if "#" not in target:
                continue
            file_part, anchor = target.split("#", 1)
            if file_part:
                # Link to a different file's anchor
                resolved = _resolve_relative_path(doc_path, file_part)
                if not resolved.exists():
                    # File existence is tested separately
                    continue
                target_content = resolved.read_text(encoding="utf-8")
            else:
                # Anchor within the same file
                target_content = content
            headings = _extract_headings(target_content)
            if anchor not in headings:
                broken.append(f"  #{anchor} not found in headings of {file_part or doc_path.name}")
        assert not broken, f"Broken anchor links in {doc_path.name}:\n" + "\n".join(broken)


# ---- Test: critical bidirectional cross-references ----


class TestCriticalCrossReferences:
    """Key cross-links between operator docs must exist in both directions."""

    def test_runbook_links_to_incident_playbooks(self) -> None:
        content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")
        assert "incident-response-playbooks.md" in content

    def test_runbook_links_to_verification_runbook(self) -> None:
        content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")
        assert "operator-verification-runbook.md" in content

    def test_incident_playbooks_links_to_runbook(self) -> None:
        content = _OPERATOR_DOCS["incident"].read_text(encoding="utf-8")
        assert "production-deployment-runbook.md" in content

    def test_incident_links_to_verification_runbook(self) -> None:
        content = _OPERATOR_DOCS["incident"].read_text(encoding="utf-8")
        assert "operator-verification-runbook.md" in content

    def test_incident_links_to_process_registry_runbook(self) -> None:
        content = _OPERATOR_DOCS["incident"].read_text(encoding="utf-8")
        assert "process-registry-runbook.md" in content

    def test_runbook_links_to_scaling_architecture(self) -> None:
        content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")
        assert "horizontal-scaling-architecture.md" in content

    def test_scaling_links_to_runbook(self) -> None:
        content = _OPERATOR_DOCS["scaling"].read_text(encoding="utf-8")
        assert "production-deployment-runbook.md" in content

    def test_runbook_links_to_monitoring_readme(self) -> None:
        content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")
        assert "deploy/monitoring/README.md" in content

    def test_slo_links_to_alert_rules(self) -> None:
        content = _OPERATOR_DOCS["slo"].read_text(encoding="utf-8")
        assert "agent33-alerts.rules.yaml" in content

    def test_slo_links_to_pricing_effort_runbook(self) -> None:
        content = _OPERATOR_DOCS["slo"].read_text(encoding="utf-8")
        assert "pricing-and-effort-runbook.md" in content

    def test_pricing_effort_runbook_links_to_slo(self) -> None:
        content = _OPERATOR_DOCS["pricing_effort"].read_text(encoding="utf-8")
        assert "service-level-objectives.md" in content

    def test_incident_links_to_alert_rules(self) -> None:
        content = _OPERATOR_DOCS["incident"].read_text(encoding="utf-8")
        assert "agent33-alerts.rules.yaml" in content

    def test_incident_links_to_slo(self) -> None:
        content = _OPERATOR_DOCS["incident"].read_text(encoding="utf-8")
        assert "service-level-objectives.md" in content

    def test_slo_links_to_incident(self) -> None:
        content = _OPERATOR_DOCS["slo"].read_text(encoding="utf-8")
        assert "incident-response-playbooks.md" in content

    def test_slo_links_to_runbook(self) -> None:
        content = _OPERATOR_DOCS["slo"].read_text(encoding="utf-8")
        assert "production-deployment-runbook.md" in content

    def test_scaling_links_to_incident(self) -> None:
        content = _OPERATOR_DOCS["scaling"].read_text(encoding="utf-8")
        assert "incident-response-playbooks.md" in content

    def test_scaling_links_to_slo(self) -> None:
        content = _OPERATOR_DOCS["scaling"].read_text(encoding="utf-8")
        assert "service-level-objectives.md" in content

    def test_runbook_links_to_slo(self) -> None:
        content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")
        assert "service-level-objectives.md" in content

    def test_runbook_links_to_connector_boundary(self) -> None:
        content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")
        assert "connector-boundary-runbook.md" in content

    def test_connector_boundary_links_to_runbook(self) -> None:
        content = _OPERATOR_DOCS["connector_boundary"].read_text(encoding="utf-8")
        assert "production-deployment-runbook.md" in content

    def test_connector_boundary_links_to_slo(self) -> None:
        content = _OPERATOR_DOCS["connector_boundary"].read_text(encoding="utf-8")
        assert "service-level-objectives.md" in content

    def test_connector_boundary_links_to_incident(self) -> None:
        content = _OPERATOR_DOCS["connector_boundary"].read_text(encoding="utf-8")
        assert "incident-response-playbooks.md" in content

    def test_verification_links_to_runbook(self) -> None:
        content = _OPERATOR_DOCS["verification"].read_text(encoding="utf-8")
        assert "production-deployment-runbook.md" in content

    def test_verification_links_to_incident(self) -> None:
        content = _OPERATOR_DOCS["verification"].read_text(encoding="utf-8")
        assert "incident-response-playbooks.md" in content

    def test_verification_links_to_process_registry(self) -> None:
        content = _OPERATOR_DOCS["verification"].read_text(encoding="utf-8")
        assert "process-registry-runbook.md" in content

    def test_process_registry_links_to_runbook(self) -> None:
        content = _OPERATOR_DOCS["process_registry"].read_text(encoding="utf-8")
        assert "production-deployment-runbook.md" in content

    def test_process_registry_links_to_incident(self) -> None:
        content = _OPERATOR_DOCS["process_registry"].read_text(encoding="utf-8")
        assert "incident-response-playbooks.md" in content

    def test_process_registry_links_to_verification(self) -> None:
        content = _OPERATOR_DOCS["process_registry"].read_text(encoding="utf-8")
        assert "operator-verification-runbook.md" in content


# ---- Test: monitoring README references operator docs ----


class TestMonitoringReadmeBacklinks:
    """deploy/monitoring/README.md must reference key operator docs."""

    def test_monitoring_readme_references_slo(self) -> None:
        content = _MONITORING_README.read_text(encoding="utf-8")
        assert "docs/operators/service-level-objectives.md" in content

    def test_monitoring_readme_references_runbook(self) -> None:
        content = _MONITORING_README.read_text(encoding="utf-8")
        assert "docs/operators/production-deployment-runbook.md" in content

    def test_monitoring_readme_references_incident_playbooks(self) -> None:
        content = _MONITORING_README.read_text(encoding="utf-8")
        assert "docs/operators/incident-response-playbooks.md" in content


# ---- Test: runbook references actual K8s manifest files ----


class TestRunbookK8sReferences:
    """Runbook file path references must map to real files in deploy/."""

    _K8S_FILES = [
        _REPO_ROOT / "deploy" / "k8s" / "base" / "api-secret.example.yaml",
        _REPO_ROOT / "deploy" / "k8s" / "base" / "postgres-secret.example.yaml",
        _REPO_ROOT / "deploy" / "k8s" / "base" / "api-service.yaml",
        _REPO_ROOT / "deploy" / "k8s" / "overlays" / "production" / "api-deployment-patch.yaml",
    ]

    def test_k8s_manifest_files_exist(self) -> None:
        content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")
        missing: list[str] = []
        for path in self._K8S_FILES:
            if not path.exists():
                missing.append(str(path))
            # Also verify the file name is actually mentioned in the runbook
            assert path.name in content, (
                f"Manifest {path.name} exists but is not referenced in runbook"
            )
        assert not missing, f"Missing K8s manifests: {missing}"

    def test_monitoring_assets_exist(self) -> None:
        grafana = (
            _REPO_ROOT
            / "deploy"
            / "monitoring"
            / "grafana"
            / "agent33-production-overview.dashboard.json"
        )
        prometheus = (
            _REPO_ROOT / "deploy" / "monitoring" / "prometheus" / "agent33-alerts.rules.yaml"
        )
        assert grafana.exists(), f"Missing: {grafana}"
        assert prometheus.exists(), f"Missing: {prometheus}"

        content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")
        assert grafana.name in content
        assert prometheus.name in content


# ---- Test: runbook Docker Compose smoke test section ----


class TestRunbookDockerCompose:
    """Runbook Docker Compose section must reference files that exist."""

    def test_docker_compose_file_exists(self) -> None:
        dc = _REPO_ROOT / "engine" / "docker-compose.yml"
        assert dc.exists(), f"Missing: {dc}"

    def test_smoke_test_script_exists(self) -> None:
        script = _REPO_ROOT / "scripts" / "docker-smoke-test.sh"
        assert script.exists(), f"Missing: {script}"

    def test_smoke_test_workflow_exists(self) -> None:
        workflow = _REPO_ROOT / ".github" / "workflows" / "docker-smoke.yml"
        assert workflow.exists(), f"Missing: {workflow}"

    def test_runbook_mentions_smoke_test(self) -> None:
        content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")
        assert "docker-smoke-test.sh" in content
        assert "docker-smoke.yml" in content
        assert "docker-compose.yml" in content


# ---- Test: all operator docs exist ----


class TestOperatorDocsExist:
    """All expected operator documentation files must be present."""

    def test_all_operator_docs_exist(self) -> None:
        missing = [name for name, path in _OPERATOR_DOCS.items() if not path.exists()]
        assert not missing, f"Missing operator docs: {missing}"

    def test_monitoring_readme_exists(self) -> None:
        assert _MONITORING_README.exists()

    def test_k8s_base_readme_exists(self) -> None:
        readme = _REPO_ROOT / "deploy" / "k8s" / "base" / "README.md"
        assert readme.exists()

    def test_k8s_production_overlay_readme_exists(self) -> None:
        readme = _REPO_ROOT / "deploy" / "k8s" / "overlays" / "production" / "README.md"
        assert readme.exists()


# ---- Test: Prometheus alert rule names mentioned in SLO doc exist in rule file ----


class TestAlertRuleConsistency:
    """Alert rule names referenced in operator docs must match the rule file."""

    _EXPECTED_ALERT_NAMES = {
        "Agent33EffortTelemetryExportFailures",
        "Agent33HighEffortRoutingRatio",
        "Agent33EstimatedCostDrift",
        "Agent33HighErrorRate",
        "Agent33HighLatency",
    }

    def test_slo_doc_alert_names_in_rules_file(self) -> None:
        rules_path = (
            _REPO_ROOT / "deploy" / "monitoring" / "prometheus" / "agent33-alerts.rules.yaml"
        )
        rules_content = rules_path.read_text(encoding="utf-8")
        slo_content = _OPERATOR_DOCS["slo"].read_text(encoding="utf-8")

        for alert_name in self._EXPECTED_ALERT_NAMES:
            assert alert_name in slo_content, f"Alert {alert_name} not mentioned in SLO doc"
            assert alert_name in rules_content, f"Alert {alert_name} not found in rules file"

    def test_runbook_alert_names_in_rules_file(self) -> None:
        rules_path = (
            _REPO_ROOT / "deploy" / "monitoring" / "prometheus" / "agent33-alerts.rules.yaml"
        )
        rules_content = rules_path.read_text(encoding="utf-8")
        runbook_content = _OPERATOR_DOCS["runbook"].read_text(encoding="utf-8")

        # The runbook mentions these specific alert names
        for alert_name in [
            "Agent33EffortTelemetryExportFailures",
            "Agent33HighEffortRoutingRatio",
            "Agent33EstimatedCostDrift",
        ]:
            assert alert_name in runbook_content, f"Alert {alert_name} not mentioned in runbook"
            assert alert_name in rules_content, f"Alert {alert_name} not found in rules file"
