"""Tests for P65: Quick-Start Operator Templates.

Validates that all 8 quick-start templates exist, parse correctly,
load through the TemplateCatalog, carry sample_inputs, and that the
new /sample API endpoint works.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from agent33.workflows.definition import WorkflowDefinition
from agent33.workflows.template_catalog import TemplateCatalog, TemplateSummary

TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "core" / "templates"

TEMPLATE_NAMES = [
    "personal-assistant",
    "research-assistant",
    "document-summarizer",
    "meeting-notes",
    "writing-helper",
    "code-review",
    "ticket-triage",
    "data-extractor",
]


# ---------------------------------------------------------------------------
# File-level validation
# ---------------------------------------------------------------------------


def test_all_eight_templates_exist() -> None:
    """Every expected template YAML file must be present on disk."""
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        assert path.exists(), f"Template file missing: {path}"


def test_all_templates_have_valid_yaml() -> None:
    """Each template file must parse as a valid YAML dict with required keys."""
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, dict), f"{name}: YAML root is not a dict"
        for key in ("name", "version", "steps", "inputs"):
            assert key in data, f"{name}: missing required key '{key}'"


def test_all_templates_have_sample_inputs() -> None:
    """Each template must carry a non-empty sample_inputs mapping."""
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "sample_inputs" in data, f"{name}: missing sample_inputs"
        assert isinstance(data["sample_inputs"], dict), f"{name}: sample_inputs not dict"
        assert len(data["sample_inputs"]) > 0, f"{name}: sample_inputs is empty"


def test_sample_inputs_cover_all_required_params() -> None:
    """sample_inputs must include a value for every required input parameter."""
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        required_keys = {k for k, v in data.get("inputs", {}).items() if v.get("required")}
        sample_keys = set(data.get("sample_inputs", {}).keys())
        missing = required_keys - sample_keys
        assert not missing, f"{name}: sample_inputs missing required keys: {missing}"


# ---------------------------------------------------------------------------
# WorkflowDefinition Pydantic validation
# ---------------------------------------------------------------------------


def test_all_templates_load_as_workflow_definition() -> None:
    """Each template must pass full WorkflowDefinition Pydantic validation."""
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        # sample_inputs is an extension field, not part of WorkflowDefinition
        data.pop("sample_inputs", None)
        defn = WorkflowDefinition.model_validate(data)
        assert defn.name == name, f"Expected name '{name}', got '{defn.name}'"


def test_template_step_ids_are_kebab_case() -> None:
    """All step IDs must match kebab-case pattern (matching WorkflowStep regex)."""
    pattern = re.compile(r"^[a-z][a-z0-9_-]*$")
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for step in data.get("steps", []):
            step_id = step["id"]
            assert pattern.match(step_id), (
                f"{name}: step id '{step_id}' violates kebab-case pattern"
            )


def test_template_names_match_filenames() -> None:
    """The 'name' field inside each YAML must match the filename stem."""
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data["name"] == name, (
            f"YAML name '{data['name']}' does not match filename stem '{name}'"
        )


# ---------------------------------------------------------------------------
# TemplateCatalog integration
# ---------------------------------------------------------------------------


def test_template_catalog_loads_all_quick_start_templates() -> None:
    """TemplateCatalog.refresh() must discover and load all 8 templates."""
    catalog = TemplateCatalog(TEMPLATES_DIR)
    count = catalog.refresh()
    assert count == len(TEMPLATE_NAMES), (
        f"Expected {len(TEMPLATE_NAMES)} templates, catalog loaded {count}"
    )
    loaded_names = {s.name for s in catalog.list_templates()}
    for name in TEMPLATE_NAMES:
        assert name in loaded_names, f"Template '{name}' not loaded by TemplateCatalog"


def test_template_summary_has_sample_inputs() -> None:
    """Every TemplateSummary produced by the catalog must carry sample_inputs."""
    catalog = TemplateCatalog(TEMPLATES_DIR)
    catalog.refresh()
    for summary in catalog.list_templates():
        assert summary.sample_inputs is not None, (
            f"{summary.name}: TemplateSummary.sample_inputs is None"
        )
        assert isinstance(summary.sample_inputs, dict)
        assert len(summary.sample_inputs) > 0, f"{summary.name}: sample_inputs is empty"


def test_template_catalog_get_template_returns_sample_inputs() -> None:
    """get_template() must return a summary with populated sample_inputs."""
    catalog = TemplateCatalog(TEMPLATES_DIR)
    catalog.refresh()
    summary = catalog.get_template("personal-assistant")
    assert summary is not None
    assert summary.sample_inputs is not None
    assert "request" in summary.sample_inputs


def test_template_catalog_add_directory() -> None:
    """add_directory() must merge templates into an existing catalog."""
    catalog = TemplateCatalog()  # no initial dir
    count = catalog.add_directory(TEMPLATES_DIR)
    assert count == len(TEMPLATE_NAMES)
    assert len(catalog.list_templates()) == len(TEMPLATE_NAMES)


def test_template_catalog_add_directory_nonexistent() -> None:
    """add_directory() on a missing path must return 0 without raising."""
    catalog = TemplateCatalog()
    count = catalog.add_directory("/nonexistent/path/does/not/exist")
    assert count == 0


def test_template_catalog_tag_filtering() -> None:
    """Tag filtering must work across quick-start templates."""
    catalog = TemplateCatalog(TEMPLATES_DIR)
    catalog.refresh()
    research_templates = catalog.list_templates(tags=["research"])
    assert any(t.name == "research-assistant" for t in research_templates)
    # Ensure non-matching templates are excluded
    assert not any(t.name == "meeting-notes" for t in research_templates)


def test_get_schema_for_quick_start_template() -> None:
    """get_schema() must return valid input/output schema for each template."""
    catalog = TemplateCatalog(TEMPLATES_DIR)
    catalog.refresh()
    for name in TEMPLATE_NAMES:
        schema = catalog.get_schema(name)
        assert schema is not None, f"Schema is None for {name}"
        assert schema.template_id == name
        assert len(schema.inputs) > 0, f"No inputs in schema for {name}"


def test_get_definition_dict_for_quick_start_template() -> None:
    """get_definition_dict() must return a serializable dict for each template."""
    catalog = TemplateCatalog(TEMPLATES_DIR)
    catalog.refresh()
    for name in TEMPLATE_NAMES:
        defn_dict = catalog.get_definition_dict(name)
        assert defn_dict is not None, f"Definition dict is None for {name}"
        assert defn_dict["name"] == name
        assert len(defn_dict["steps"]) >= 1


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def _make_catalog() -> TemplateCatalog:
    """Helper to create a populated catalog for route tests."""
    catalog = TemplateCatalog(TEMPLATES_DIR)
    catalog.refresh()
    return catalog


@pytest.fixture()
def _populated_catalog() -> TemplateCatalog:
    return _make_catalog()


async def test_sample_endpoint_logic_happy_path(
    _populated_catalog: TemplateCatalog,
) -> None:
    """Verify the sample endpoint handler returns correct data when called directly."""
    from agent33.api.routes.workflow_templates import get_template_sample

    with patch(
        "agent33.api.routes.workflow_templates.get_template_catalog",
        return_value=_populated_catalog,
    ):
        result: dict[str, Any] = await get_template_sample("personal-assistant")
    assert isinstance(result, dict)
    assert "request" in result
    assert "plan my week" in result["request"].lower()


async def test_sample_endpoint_logic_not_found(
    _populated_catalog: TemplateCatalog,
) -> None:
    """Verify the sample endpoint raises 404 for unknown template IDs."""
    from fastapi import HTTPException

    from agent33.api.routes.workflow_templates import get_template_sample

    with (
        patch(
            "agent33.api.routes.workflow_templates.get_template_catalog",
            return_value=_populated_catalog,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_template_sample("nonexistent-template")
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


async def test_sample_endpoint_logic_no_sample_inputs() -> None:
    """Verify the sample endpoint raises 404 when template has no sample_inputs."""
    from fastapi import HTTPException

    from agent33.api.routes.workflow_templates import get_template_sample

    # Create a catalog with a template that has no sample_inputs
    catalog = TemplateCatalog()
    catalog._templates["bare-template"] = TemplateSummary(
        id="bare-template",
        name="bare-template",
        version="1.0.0",
        source_path="test/bare.workflow.yaml",
        step_count=1,
        sample_inputs=None,
    )

    with (
        patch(
            "agent33.api.routes.workflow_templates.get_template_catalog",
            return_value=catalog,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_template_sample("bare-template")
    assert exc_info.value.status_code == 404
    assert "no sample inputs" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Content quality checks
# ---------------------------------------------------------------------------


def test_templates_use_known_agent_names() -> None:
    """Every step must reference an agent that exists in the agent-definitions."""
    known_agents = {"orchestrator", "director", "code-worker", "qa", "researcher", "browser-agent"}
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for step in data.get("steps", []):
            agent = step.get("agent")
            if agent:
                assert agent in known_agents, (
                    f"{name}: step '{step['id']}' uses unknown agent '{agent}'"
                )


def test_all_templates_have_metadata_tags() -> None:
    """Every template should carry at least one metadata tag."""
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        tags = data.get("metadata", {}).get("tags", [])
        assert len(tags) >= 1, f"{name}: no metadata tags"


def test_all_templates_have_descriptions() -> None:
    """Every template must have a non-empty description."""
    for name in TEMPLATE_NAMES:
        path = TEMPLATES_DIR / f"{name}.workflow.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        desc = data.get("description", "")
        assert desc and len(desc.strip()) > 10, f"{name}: description too short or missing"
