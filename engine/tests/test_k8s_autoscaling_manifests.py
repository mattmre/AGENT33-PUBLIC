"""Validation for K8s autoscaling manifests (HPA, PDB, resource limits)."""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE_DIR = _REPO_ROOT / "deploy" / "k8s" / "base"
_PROD_DIR = _REPO_ROOT / "deploy" / "k8s" / "overlays" / "production"

_HPA_PATH = _BASE_DIR / "api-hpa.yaml"
_PDB_PATH = _BASE_DIR / "api-pdb.yaml"
_DEPLOYMENT_PATH = _BASE_DIR / "api-deployment.yaml"
_BASE_KUSTOMIZATION_PATH = _BASE_DIR / "kustomization.yaml"
_PROD_KUSTOMIZATION_PATH = _PROD_DIR / "kustomization.yaml"
_PROD_HPA_PATCH_PATH = _PROD_DIR / "api-hpa-patch.yaml"


# ---------------------------------------------------------------------------
# HPA manifest tests
# ---------------------------------------------------------------------------


def test_hpa_is_valid_yaml_with_correct_api_version() -> None:
    hpa = yaml.safe_load(_HPA_PATH.read_text(encoding="utf-8"))
    assert hpa["apiVersion"] == "autoscaling/v2"
    assert hpa["kind"] == "HorizontalPodAutoscaler"


def test_hpa_targets_correct_deployment() -> None:
    hpa = yaml.safe_load(_HPA_PATH.read_text(encoding="utf-8"))
    target = hpa["spec"]["scaleTargetRef"]
    assert target["apiVersion"] == "apps/v1"
    assert target["kind"] == "Deployment"
    assert target["name"] == "agent33-api"


def test_hpa_max_replicas_is_one_guardrail() -> None:
    """maxReplicas must be 1 until all single-instance blockers are resolved."""
    hpa = yaml.safe_load(_HPA_PATH.read_text(encoding="utf-8"))
    assert hpa["spec"]["maxReplicas"] == 1
    assert hpa["spec"]["minReplicas"] == 1


def test_hpa_has_cpu_and_memory_metrics() -> None:
    hpa = yaml.safe_load(_HPA_PATH.read_text(encoding="utf-8"))
    metrics = hpa["spec"]["metrics"]
    resource_names = {m["resource"]["name"] for m in metrics if m["type"] == "Resource"}
    assert "cpu" in resource_names
    assert "memory" in resource_names


def test_hpa_cpu_target_utilization() -> None:
    hpa = yaml.safe_load(_HPA_PATH.read_text(encoding="utf-8"))
    cpu_metric = next(
        m
        for m in hpa["spec"]["metrics"]
        if m["type"] == "Resource" and m["resource"]["name"] == "cpu"
    )
    assert cpu_metric["resource"]["target"]["type"] == "Utilization"
    assert cpu_metric["resource"]["target"]["averageUtilization"] == 75


def test_hpa_memory_target_utilization() -> None:
    hpa = yaml.safe_load(_HPA_PATH.read_text(encoding="utf-8"))
    mem_metric = next(
        m
        for m in hpa["spec"]["metrics"]
        if m["type"] == "Resource" and m["resource"]["name"] == "memory"
    )
    assert mem_metric["resource"]["target"]["type"] == "Utilization"
    assert mem_metric["resource"]["target"]["averageUtilization"] == 80


def test_hpa_scale_down_stabilization_window() -> None:
    hpa = yaml.safe_load(_HPA_PATH.read_text(encoding="utf-8"))
    scale_down = hpa["spec"]["behavior"]["scaleDown"]
    assert scale_down["stabilizationWindowSeconds"] == 300


def test_hpa_scale_up_stabilization_window() -> None:
    hpa = yaml.safe_load(_HPA_PATH.read_text(encoding="utf-8"))
    scale_up = hpa["spec"]["behavior"]["scaleUp"]
    assert scale_up["stabilizationWindowSeconds"] == 60


# ---------------------------------------------------------------------------
# PDB manifest tests
# ---------------------------------------------------------------------------


def test_pdb_is_valid_yaml_with_correct_api_version() -> None:
    pdb = yaml.safe_load(_PDB_PATH.read_text(encoding="utf-8"))
    assert pdb["apiVersion"] == "policy/v1"
    assert pdb["kind"] == "PodDisruptionBudget"


def test_pdb_min_available_is_one() -> None:
    pdb = yaml.safe_load(_PDB_PATH.read_text(encoding="utf-8"))
    assert pdb["spec"]["minAvailable"] == 1


def test_pdb_selector_matches_deployment_labels() -> None:
    pdb = yaml.safe_load(_PDB_PATH.read_text(encoding="utf-8"))
    deployment = yaml.safe_load(_DEPLOYMENT_PATH.read_text(encoding="utf-8"))

    pdb_selector = pdb["spec"]["selector"]["matchLabels"]
    deploy_selector = deployment["spec"]["selector"]["matchLabels"]
    # PDB selector must be a subset of deployment selector to match pods
    for key, value in pdb_selector.items():
        assert deploy_selector.get(key) == value, (
            f"PDB label {key}={value} does not match deployment selector"
        )


# ---------------------------------------------------------------------------
# Deployment resource limits tests
# ---------------------------------------------------------------------------


def test_deployment_has_resource_requests() -> None:
    dep = yaml.safe_load(_DEPLOYMENT_PATH.read_text(encoding="utf-8"))
    container = dep["spec"]["template"]["spec"]["containers"][0]
    resources = container["resources"]
    assert resources["requests"]["cpu"] == "250m"
    assert resources["requests"]["memory"] == "512Mi"


def test_deployment_has_resource_limits() -> None:
    dep = yaml.safe_load(_DEPLOYMENT_PATH.read_text(encoding="utf-8"))
    container = dep["spec"]["template"]["spec"]["containers"][0]
    resources = container["resources"]
    assert resources["limits"]["cpu"] == "2"
    assert resources["limits"]["memory"] == "2Gi"


# ---------------------------------------------------------------------------
# Kustomization inclusion tests
# ---------------------------------------------------------------------------


def test_base_kustomization_includes_hpa() -> None:
    kustom = yaml.safe_load(_BASE_KUSTOMIZATION_PATH.read_text(encoding="utf-8"))
    assert "api-hpa.yaml" in kustom["resources"]


def test_base_kustomization_includes_pdb() -> None:
    kustom = yaml.safe_load(_BASE_KUSTOMIZATION_PATH.read_text(encoding="utf-8"))
    assert "api-pdb.yaml" in kustom["resources"]


# ---------------------------------------------------------------------------
# Production overlay tests
# ---------------------------------------------------------------------------


def test_production_overlay_hpa_patch_exists() -> None:
    patch = yaml.safe_load(_PROD_HPA_PATCH_PATH.read_text(encoding="utf-8"))
    assert patch["apiVersion"] == "autoscaling/v2"
    assert patch["kind"] == "HorizontalPodAutoscaler"
    assert patch["metadata"]["name"] == "agent33-api"


def test_production_overlay_hpa_patch_enforces_guardrail() -> None:
    patch = yaml.safe_load(_PROD_HPA_PATCH_PATH.read_text(encoding="utf-8"))
    assert patch["spec"]["maxReplicas"] == 1


def test_production_kustomization_includes_hpa_patch() -> None:
    kustom = yaml.safe_load(_PROD_KUSTOMIZATION_PATH.read_text(encoding="utf-8"))
    patch_paths = [p["path"] for p in kustom["patches"]]
    assert "api-hpa-patch.yaml" in patch_paths


def test_production_overlay_hpa_patch_has_warning_comment() -> None:
    """The production HPA patch must contain a warning about the guardrail."""
    raw = _PROD_HPA_PATCH_PATH.read_text(encoding="utf-8")
    assert "horizontal-scaling-architecture.md" in raw
    assert "WARNING" in raw or "Do not increase maxReplicas" in raw
