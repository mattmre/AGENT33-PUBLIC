"""Tests for session affinity ingress, kustomization wiring, and pod middleware."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import yaml
from fastapi import FastAPI
from starlette.testclient import TestClient

from agent33.api.middleware.session_pod import SessionPodMiddleware

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE_DIR = _REPO_ROOT / "deploy" / "k8s" / "base"
_PROD_DIR = _REPO_ROOT / "deploy" / "k8s" / "overlays" / "production"

_INGRESS_PATH = _BASE_DIR / "api-ingress.yaml"
_BASE_KUSTOMIZATION_PATH = _BASE_DIR / "kustomization.yaml"
_PROD_KUSTOMIZATION_PATH = _PROD_DIR / "kustomization.yaml"
_PROD_INGRESS_PATCH_PATH = _PROD_DIR / "api-ingress-patch.yaml"

# Cookie name must be consistent between ingress manifest and operator docs.
_EXPECTED_COOKIE_NAME = "AGENT33_AFFINITY"


# ---------------------------------------------------------------------------
# Ingress manifest structure tests
# ---------------------------------------------------------------------------


def test_ingress_is_valid_yaml_with_correct_api_version() -> None:
    ingress = yaml.safe_load(_INGRESS_PATH.read_text(encoding="utf-8"))
    assert ingress["apiVersion"] == "networking.k8s.io/v1"
    assert ingress["kind"] == "Ingress"


def test_ingress_metadata_name_matches_service() -> None:
    ingress = yaml.safe_load(_INGRESS_PATH.read_text(encoding="utf-8"))
    assert ingress["metadata"]["name"] == "agent33-api"


def test_ingress_has_nginx_affinity_annotations() -> None:
    ingress = yaml.safe_load(_INGRESS_PATH.read_text(encoding="utf-8"))
    annotations = ingress["metadata"]["annotations"]

    assert annotations["nginx.ingress.kubernetes.io/affinity"] == "cookie"
    assert annotations["nginx.ingress.kubernetes.io/session-cookie-name"] == _EXPECTED_COOKIE_NAME
    assert annotations["nginx.ingress.kubernetes.io/session-cookie-expires"] == "3600"
    assert annotations["nginx.ingress.kubernetes.io/session-cookie-max-age"] == "3600"
    assert annotations["nginx.ingress.kubernetes.io/session-cookie-change-on-failure"] == "true"


def test_ingress_has_websocket_timeout_annotations() -> None:
    ingress = yaml.safe_load(_INGRESS_PATH.read_text(encoding="utf-8"))
    annotations = ingress["metadata"]["annotations"]

    assert annotations["nginx.ingress.kubernetes.io/proxy-read-timeout"] == "3600"
    assert annotations["nginx.ingress.kubernetes.io/proxy-send-timeout"] == "3600"


def test_ingress_uses_nginx_ingress_class() -> None:
    ingress = yaml.safe_load(_INGRESS_PATH.read_text(encoding="utf-8"))
    assert ingress["spec"]["ingressClassName"] == "nginx"


def test_ingress_backend_targets_api_service_on_port_8000() -> None:
    ingress = yaml.safe_load(_INGRESS_PATH.read_text(encoding="utf-8"))
    path_entry = ingress["spec"]["rules"][0]["http"]["paths"][0]

    assert path_entry["path"] == "/"
    assert path_entry["pathType"] == "Prefix"
    assert path_entry["backend"]["service"]["name"] == "agent33-api"
    assert path_entry["backend"]["service"]["port"]["number"] == 8000


def test_ingress_raw_contains_traefik_alternative_comments() -> None:
    """Traefik sticky-cookie annotations must be present as comments."""
    raw = _INGRESS_PATH.read_text(encoding="utf-8")
    assert "traefik.ingress.kubernetes.io/service.sticky.cookie" in raw
    assert _EXPECTED_COOKIE_NAME in raw


# ---------------------------------------------------------------------------
# Cookie name consistency test
# ---------------------------------------------------------------------------


def test_cookie_name_consistent_between_ingress_and_docs() -> None:
    """The affinity cookie name in the Ingress manifest must match the
    operator docs so operators can reference a single canonical name."""
    ingress = yaml.safe_load(_INGRESS_PATH.read_text(encoding="utf-8"))
    cookie_name = ingress["metadata"]["annotations"][
        "nginx.ingress.kubernetes.io/session-cookie-name"
    ]

    docs_path = _REPO_ROOT / "docs" / "operators" / "horizontal-scaling-architecture.md"
    docs_text = docs_path.read_text(encoding="utf-8")

    assert cookie_name == _EXPECTED_COOKIE_NAME
    assert _EXPECTED_COOKIE_NAME in docs_text, (
        f"Cookie name {_EXPECTED_COOKIE_NAME!r} not found in operator docs"
    )


# ---------------------------------------------------------------------------
# Kustomization inclusion tests
# ---------------------------------------------------------------------------


def test_base_kustomization_includes_ingress() -> None:
    kustom = yaml.safe_load(_BASE_KUSTOMIZATION_PATH.read_text(encoding="utf-8"))
    assert "api-ingress.yaml" in kustom["resources"]


def test_production_overlay_includes_ingress_patch() -> None:
    kustom = yaml.safe_load(_PROD_KUSTOMIZATION_PATH.read_text(encoding="utf-8"))
    patch_paths = [p["path"] for p in kustom["patches"]]
    assert "api-ingress-patch.yaml" in patch_paths


# ---------------------------------------------------------------------------
# Production overlay ingress patch tests
# ---------------------------------------------------------------------------


def test_production_ingress_patch_is_valid_yaml() -> None:
    patch = yaml.safe_load(_PROD_INGRESS_PATCH_PATH.read_text(encoding="utf-8"))
    assert patch["apiVersion"] == "networking.k8s.io/v1"
    assert patch["kind"] == "Ingress"
    assert patch["metadata"]["name"] == "agent33-api"


def test_production_ingress_patch_enforces_ssl_redirect() -> None:
    patch = yaml.safe_load(_PROD_INGRESS_PATCH_PATH.read_text(encoding="utf-8"))
    annotations = patch["metadata"]["annotations"]
    assert annotations["nginx.ingress.kubernetes.io/ssl-redirect"] == "true"


# ---------------------------------------------------------------------------
# SessionPodMiddleware tests
# ---------------------------------------------------------------------------


def _make_test_app() -> FastAPI:
    """Create a minimal FastAPI app with SessionPodMiddleware."""
    test_app = FastAPI()
    test_app.add_middleware(SessionPodMiddleware)

    @test_app.get("/test-pod")
    async def _test_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    return test_app


def test_session_pod_middleware_adds_header() -> None:
    """The middleware must add X-Agent33-Session-Pod to every response."""
    app = _make_test_app()
    client = TestClient(app)
    resp = client.get("/test-pod")

    assert resp.status_code == 200
    assert "X-Agent33-Session-Pod" in resp.headers
    # The header value should be a non-empty string
    assert len(resp.headers["X-Agent33-Session-Pod"]) > 0


def test_session_pod_middleware_uses_hostname_env() -> None:
    """When HOSTNAME env var is set (as in K8s pods), the middleware returns it."""
    app = _make_test_app()
    client = TestClient(app)

    with mock.patch.dict(os.environ, {"HOSTNAME": "agent33-api-abc123"}):
        resp = client.get("/test-pod")

    assert resp.headers["X-Agent33-Session-Pod"] == "agent33-api-abc123"


def test_session_pod_middleware_falls_back_to_computername() -> None:
    """On Windows (no HOSTNAME), falls back to COMPUTERNAME."""
    app = _make_test_app()
    client = TestClient(app)

    env = dict(os.environ)
    env.pop("HOSTNAME", None)
    env["COMPUTERNAME"] = "WIN-SERVER-01"

    with mock.patch.dict(os.environ, env, clear=True):
        resp = client.get("/test-pod")

    assert resp.headers["X-Agent33-Session-Pod"] == "WIN-SERVER-01"


def test_session_pod_middleware_falls_back_to_unknown() -> None:
    """When neither HOSTNAME nor COMPUTERNAME exist, falls back to 'unknown'."""
    app = _make_test_app()
    client = TestClient(app)

    env = dict(os.environ)
    env.pop("HOSTNAME", None)
    env.pop("COMPUTERNAME", None)

    with mock.patch.dict(os.environ, env, clear=True):
        resp = client.get("/test-pod")

    assert resp.headers["X-Agent33-Session-Pod"] == "unknown"


def test_session_pod_middleware_preserves_response_body() -> None:
    """The middleware must not alter the response body."""
    app = _make_test_app()
    client = TestClient(app)
    resp = client.get("/test-pod")

    assert resp.json() == {"status": "ok"}
