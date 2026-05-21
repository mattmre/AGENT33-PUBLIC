"""Tests for the workflow template catalog and API endpoints.

Covers: template discovery, listing with tag filters, schema endpoint,
refresh idempotency, missing directory handling, and full API routes.
"""

from __future__ import annotations

import contextlib
import textwrap
from pathlib import Path  # noqa: TCH003

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import workflow_templates, workflows
from agent33.main import app
from agent33.security import auth
from agent33.security.auth import create_access_token
from agent33.workflows.definition import WorkflowDefinition
from agent33.workflows.template_catalog import TemplateCatalog


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    """Reset global state between tests."""
    workflows.reset_workflow_state()
    if workflows._scheduler is not None:
        with contextlib.suppress(RuntimeError):
            workflows._scheduler.stop()
        workflows._scheduler = None
    auth._api_keys.clear()
    workflow_templates.set_template_catalog(None)  # type: ignore[arg-type]
    yield
    workflows.reset_workflow_state()
    auth._api_keys.clear()
    workflow_templates.set_template_catalog(None)  # type: ignore[arg-type]


def _auth_headers() -> dict[str, str]:
    token = create_access_token(
        "test-user", scopes=["workflows:read", "workflows:write"], tenant_id="t1"
    )
    return {"Authorization": f"Bearer {token}"}


def _write_template(base_dir: Path, filename: str, content: str) -> Path:
    """Write a YAML template file to a subdirectory."""
    subdir = base_dir / "improvement-cycle"
    subdir.mkdir(parents=True, exist_ok=True)
    filepath = subdir / filename
    filepath.write_text(textwrap.dedent(content), encoding="utf-8")
    return filepath


def _minimal_template_yaml(name: str = "test-template", tags: str = "") -> str:
    tag_block = ""
    if tags:
        tag_block = f"""
  tags:
    - {tags}"""
    return f"""\
name: {name}
version: 1.0.0
description: A test workflow template.
inputs:
  session_id:
    type: string
    description: Session identifier.
    required: true
  scope:
    type: string
    description: Review scope.
    default: full-delivery
outputs:
  result:
    type: object
    description: Output scaffold.
steps:
  - id: validate
    name: Validate input
    action: validate
    inputs:
      data: session_id
      expression: "'data'"
execution:
  mode: dependency-aware
  fail_fast: true
metadata:
  author: test{tag_block}
"""


@pytest.mark.parametrize(
    ("filename", "workflow_name", "expected_agent"),
    [
        ("docs-overhaul.workflow.yaml", "docs-overhaul", "researcher"),
        ("implementation-session.workflow.yaml", "implementation-session", "orchestrator"),
        ("pr-review-orchestration.workflow.yaml", "pr-review-orchestration", "qa"),
        ("repo-ingestion.workflow.yaml", "repo-ingestion", "researcher"),
        ("webapp-lifecycle-testing.workflow.yaml", "webapp-lifecycle-testing", "qa"),
    ],
)
def test_phase47_capability_pack_templates_load(
    filename: str,
    workflow_name: str,
    expected_agent: str,
) -> None:
    template_path = (
        Path(__file__).resolve().parents[2] / "core" / "workflows" / "capability-packs" / filename
    )

    workflow = WorkflowDefinition.load_from_file(template_path)

    assert workflow.name == workflow_name
    assert len(workflow.steps) == 1
    assert workflow.steps[0].action.value == "invoke-agent"
    assert workflow.steps[0].agent == expected_agent


# ---------------------------------------------------------------------------
# Unit tests: TemplateCatalog
# ---------------------------------------------------------------------------


class TestTemplateCatalog:
    def test_refresh_with_no_directory(self) -> None:
        catalog = TemplateCatalog(None)
        count = catalog.refresh()
        assert count == 0
        assert catalog.list_templates() == []

    def test_refresh_with_missing_directory(self, tmp_path: Path) -> None:
        catalog = TemplateCatalog(tmp_path / "nonexistent")
        count = catalog.refresh()
        assert count == 0

    def test_refresh_discovers_yaml_templates(self, tmp_path: Path) -> None:
        _write_template(
            tmp_path / "core" / "workflows",
            "test.workflow.yaml",
            _minimal_template_yaml(),
        )
        catalog = TemplateCatalog(tmp_path / "core" / "workflows")
        count = catalog.refresh()
        assert count == 1

        templates = catalog.list_templates()
        assert len(templates) == 1
        assert templates[0].name == "test-template"
        assert templates[0].version == "1.0.0"
        assert templates[0].step_count == 1
        assert "session_id" in templates[0].inputs
        assert templates[0].inputs["session_id"].required is True

    def test_refresh_is_idempotent(self, tmp_path: Path) -> None:
        _write_template(
            tmp_path / "core" / "workflows",
            "test.workflow.yaml",
            _minimal_template_yaml(),
        )
        catalog = TemplateCatalog(tmp_path / "core" / "workflows")
        catalog.refresh()
        catalog.refresh()
        assert len(catalog.list_templates()) == 1

    def test_list_templates_with_tag_filter(self, tmp_path: Path) -> None:
        workflows_dir = tmp_path / "core" / "workflows"
        _write_template(
            workflows_dir,
            "retro.workflow.yaml",
            _minimal_template_yaml("retro-template", "retrospective"),
        )
        _write_template(
            workflows_dir,
            "metrics.workflow.yaml",
            _minimal_template_yaml("metrics-template", "metrics"),
        )
        catalog = TemplateCatalog(workflows_dir)
        catalog.refresh()

        all_templates = catalog.list_templates()
        assert len(all_templates) == 2

        retro_only = catalog.list_templates(tags=["retrospective"])
        assert len(retro_only) == 1
        assert retro_only[0].name == "retro-template"

    def test_list_templates_with_limit(self, tmp_path: Path) -> None:
        workflows_dir = tmp_path / "core" / "workflows"
        _write_template(
            workflows_dir,
            "a.workflow.yaml",
            _minimal_template_yaml("a-template"),
        )
        _write_template(
            workflows_dir,
            "b.workflow.yaml",
            _minimal_template_yaml("b-template"),
        )
        catalog = TemplateCatalog(workflows_dir)
        catalog.refresh()
        limited = catalog.list_templates(limit=1)
        assert len(limited) == 1

    def test_get_template_found(self, tmp_path: Path) -> None:
        _write_template(
            tmp_path / "core" / "workflows",
            "test.workflow.yaml",
            _minimal_template_yaml(),
        )
        catalog = TemplateCatalog(tmp_path / "core" / "workflows")
        catalog.refresh()
        template = catalog.get_template("test-template")
        assert template is not None
        assert template.description == "A test workflow template."

    def test_get_template_not_found(self) -> None:
        catalog = TemplateCatalog(None)
        catalog.refresh()
        assert catalog.get_template("nonexistent") is None

    def test_get_schema(self, tmp_path: Path) -> None:
        _write_template(
            tmp_path / "core" / "workflows",
            "test.workflow.yaml",
            _minimal_template_yaml(),
        )
        catalog = TemplateCatalog(tmp_path / "core" / "workflows")
        catalog.refresh()
        schema = catalog.get_schema("test-template")
        assert schema is not None
        assert schema.template_id == "test-template"
        assert "session_id" in schema.inputs
        assert schema.inputs["session_id"].type == "string"
        assert schema.inputs["session_id"].required is True
        assert "scope" in schema.inputs
        assert schema.inputs["scope"].default == "full-delivery"

    def test_get_definition_dict(self, tmp_path: Path) -> None:
        _write_template(
            tmp_path / "core" / "workflows",
            "test.workflow.yaml",
            _minimal_template_yaml(),
        )
        catalog = TemplateCatalog(tmp_path / "core" / "workflows")
        catalog.refresh()
        defn = catalog.get_definition_dict("test-template")
        assert defn is not None
        assert defn["name"] == "test-template"
        assert len(defn["steps"]) == 1

    def test_skips_invalid_yaml(self, tmp_path: Path) -> None:
        workflows_dir = tmp_path / "core" / "workflows"
        subdir = workflows_dir / "improvement-cycle"
        subdir.mkdir(parents=True)
        (subdir / "bad.workflow.yaml").write_text("not: valid: {yaml", encoding="utf-8")
        catalog = TemplateCatalog(workflows_dir)
        count = catalog.refresh()
        assert count == 0


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


def _setup_catalog_with_template(
    tmp_path: Path, name: str = "test-template", tags: str = ""
) -> TemplateCatalog:
    """Create and register a catalog with one template."""
    _write_template(
        tmp_path / "core" / "workflows",
        f"{name}.workflow.yaml",
        _minimal_template_yaml(name, tags),
    )
    catalog = TemplateCatalog(tmp_path / "core" / "workflows")
    catalog.refresh()
    workflow_templates.set_template_catalog(catalog)
    return catalog


class TestWorkflowTemplatesAPI:
    def test_list_templates_returns_catalog(self, tmp_path: Path) -> None:
        _setup_catalog_with_template(tmp_path)
        client = TestClient(app)
        resp = client.get("/v1/workflows/templates/", headers=_auth_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["templates"]) == 1
        template = body["templates"][0]
        assert template["name"] == "test-template"
        assert template["step_count"] == 1
        assert "session_id" in template["inputs"]

    def test_list_templates_tag_filter(self, tmp_path: Path) -> None:
        workflows_dir = tmp_path / "core" / "workflows"
        _write_template(
            workflows_dir,
            "retro.workflow.yaml",
            _minimal_template_yaml("retro-template", "retrospective"),
        )
        _write_template(
            workflows_dir,
            "metrics.workflow.yaml",
            _minimal_template_yaml("metrics-template", "metrics"),
        )
        catalog = TemplateCatalog(workflows_dir)
        catalog.refresh()
        workflow_templates.set_template_catalog(catalog)

        client = TestClient(app)
        resp = client.get(
            "/v1/workflows/templates/",
            params={"tags": "retrospective"},
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        templates = resp.json()["templates"]
        assert len(templates) == 1
        assert templates[0]["name"] == "retro-template"

    def test_get_template_by_id(self, tmp_path: Path) -> None:
        _setup_catalog_with_template(tmp_path)
        client = TestClient(app)
        resp = client.get("/v1/workflows/templates/test-template", headers=_auth_headers())
        assert resp.status_code == 200
        assert resp.json()["name"] == "test-template"

    def test_get_template_not_found(self, tmp_path: Path) -> None:
        _setup_catalog_with_template(tmp_path)
        client = TestClient(app)
        resp = client.get("/v1/workflows/templates/nonexistent", headers=_auth_headers())
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    def test_get_template_schema(self, tmp_path: Path) -> None:
        _setup_catalog_with_template(tmp_path)
        client = TestClient(app)
        resp = client.get(
            "/v1/workflows/templates/test-template/schema",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["template_id"] == "test-template"
        assert "session_id" in body["inputs"]
        assert body["inputs"]["session_id"]["type"] == "string"
        assert body["inputs"]["session_id"]["required"] is True
        assert "scope" in body["inputs"]
        assert body["inputs"]["scope"]["default"] == "full-delivery"

    def test_get_template_schema_not_found(self, tmp_path: Path) -> None:
        _setup_catalog_with_template(tmp_path)
        client = TestClient(app)
        resp = client.get(
            "/v1/workflows/templates/nonexistent/schema",
            headers=_auth_headers(),
        )
        assert resp.status_code == 404

    def test_get_template_definition(self, tmp_path: Path) -> None:
        _setup_catalog_with_template(tmp_path)
        client = TestClient(app)
        resp = client.get(
            "/v1/workflows/templates/test-template/definition",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        defn = resp.json()
        assert defn["name"] == "test-template"
        assert len(defn["steps"]) == 1

    def test_refresh_endpoint(self, tmp_path: Path) -> None:
        _setup_catalog_with_template(tmp_path)
        client = TestClient(app)
        resp = client.post(
            "/v1/workflows/templates/refresh",
            headers=_auth_headers(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["refreshed"] is True
        assert body["template_count"] == 1

    def test_catalog_not_initialized_returns_503(self) -> None:
        client = TestClient(app)
        resp = client.get("/v1/workflows/templates/", headers=_auth_headers())
        assert resp.status_code == 503
        assert "not initialized" in resp.json()["detail"]

    def test_auth_required(self, tmp_path: Path) -> None:
        _setup_catalog_with_template(tmp_path)
        client = TestClient(app)
        resp = client.get("/v1/workflows/templates/")
        assert resp.status_code == 401
