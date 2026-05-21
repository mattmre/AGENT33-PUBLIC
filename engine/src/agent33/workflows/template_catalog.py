"""Workflow template catalog: discovers and caches canonical workflow templates.

Scans a directory of YAML workflow definitions at startup and provides
read-only access to template metadata and input/output schemas.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from agent33.workflows.definition import ParameterDef, WorkflowDefinition

logger = logging.getLogger(__name__)


class TemplateSummary(BaseModel):
    """Read-only summary of a discovered workflow template."""

    id: str
    name: str
    version: str
    description: str | None = None
    source_path: str
    inputs: dict[str, ParameterDef] = Field(default_factory=dict)
    outputs: dict[str, ParameterDef] = Field(default_factory=dict)
    step_count: int
    tags: list[str] = Field(default_factory=list)
    sample_inputs: dict[str, Any] | None = None


class TemplateSchema(BaseModel):
    """Input/output schema for a specific template."""

    template_id: str
    inputs: dict[str, ParameterDef] = Field(default_factory=dict)
    outputs: dict[str, ParameterDef] = Field(default_factory=dict)


class TemplateCatalog:
    """In-memory catalog of canonical workflow templates.

    Templates are loaded from YAML files in a directory tree. The catalog is
    read-only and can be refreshed by re-scanning the source directory.
    """

    def __init__(self, template_dir: str | Path | None = None) -> None:
        self._template_dir = Path(template_dir) if template_dir else None
        self._templates: dict[str, TemplateSummary] = {}
        self._definitions: dict[str, WorkflowDefinition] = {}

    @property
    def template_dir(self) -> Path | None:
        return self._template_dir

    def refresh(self) -> int:
        """Re-scan the template directory and reload all definitions.

        Returns the number of templates loaded. If the template directory
        does not exist or is not set, returns 0 without error.
        """
        self._templates.clear()
        self._definitions.clear()

        if self._template_dir is None:
            logger.info("template_catalog_no_dir_configured")
            return 0

        if not self._template_dir.is_dir():
            logger.warning(
                "template_catalog_dir_missing path=%s",
                str(self._template_dir),
            )
            return 0

        count = 0
        for yaml_path in sorted(self._template_dir.rglob("*.workflow.yaml")):
            try:
                raw_text = yaml_path.read_text(encoding="utf-8")
                raw_data = yaml.safe_load(raw_text)
                sample_inputs: dict[str, Any] | None = (
                    raw_data.get("sample_inputs") if isinstance(raw_data, dict) else None
                )
                definition = WorkflowDefinition.load_from_file(yaml_path)
            except Exception as exc:
                logger.warning(
                    "template_catalog_load_failed path=%s error=%s",
                    str(yaml_path),
                    str(exc),
                )
                continue

            template_id = definition.name
            # Compute relative path; fall back to file name if outside expected tree
            try:
                relative_path = str(yaml_path.relative_to(self._template_dir.parent.parent))
            except ValueError:
                relative_path = str(yaml_path.relative_to(self._template_dir))

            tags = list(definition.metadata.tags) if definition.metadata.tags else []

            summary = TemplateSummary(
                id=template_id,
                name=definition.name,
                version=definition.version,
                description=definition.description,
                source_path=relative_path,
                inputs=definition.inputs,
                outputs=definition.outputs,
                step_count=len(definition.steps),
                tags=tags,
                sample_inputs=sample_inputs,
            )
            self._templates[template_id] = summary
            self._definitions[template_id] = definition
            count += 1

        logger.info("template_catalog_refreshed count=%d", count)
        return count

    def add_directory(self, directory: str | Path) -> int:
        """Scan an additional directory and merge templates into the catalog.

        Unlike ``refresh()``, this does **not** clear existing entries. Templates
        from the new directory are added (or overwrite same-id entries) on top of
        what is already loaded.

        Returns the number of templates loaded from *directory*.
        """
        dir_path = Path(directory)
        if not dir_path.is_dir():
            logger.warning(
                "template_catalog_add_dir_missing path=%s",
                str(dir_path),
            )
            return 0

        count = 0
        for yaml_path in sorted(dir_path.rglob("*.workflow.yaml")):
            try:
                raw_text = yaml_path.read_text(encoding="utf-8")
                raw_data = yaml.safe_load(raw_text)
                sample_inputs: dict[str, Any] | None = (
                    raw_data.get("sample_inputs") if isinstance(raw_data, dict) else None
                )
                definition = WorkflowDefinition.load_from_file(yaml_path)
            except Exception as exc:
                logger.warning(
                    "template_catalog_load_failed path=%s error=%s",
                    str(yaml_path),
                    str(exc),
                )
                continue

            template_id = definition.name
            try:
                relative_path = str(yaml_path.relative_to(dir_path.parent.parent))
            except ValueError:
                relative_path = str(yaml_path.relative_to(dir_path))

            tags = list(definition.metadata.tags) if definition.metadata.tags else []

            summary = TemplateSummary(
                id=template_id,
                name=definition.name,
                version=definition.version,
                description=definition.description,
                source_path=relative_path,
                inputs=definition.inputs,
                outputs=definition.outputs,
                step_count=len(definition.steps),
                tags=tags,
                sample_inputs=sample_inputs,
            )
            self._templates[template_id] = summary
            self._definitions[template_id] = definition
            count += 1

        logger.info("template_catalog_added_directory count=%d path=%s", count, str(dir_path))
        return count

    def list_templates(
        self,
        *,
        tags: list[str] | None = None,
        limit: int | None = None,
    ) -> list[TemplateSummary]:
        """Return all templates, optionally filtered by tags."""
        results = list(self._templates.values())

        if tags:
            tag_set = set(tags)
            results = [t for t in results if tag_set.intersection(t.tags)]

        if limit is not None and limit > 0:
            results = results[:limit]

        return results

    def get_template(self, template_id: str) -> TemplateSummary | None:
        """Return a template summary by ID, or ``None`` if not found."""
        return self._templates.get(template_id)

    def get_schema(self, template_id: str) -> TemplateSchema | None:
        """Return the input/output schema for a template."""
        summary = self._templates.get(template_id)
        if summary is None:
            return None
        return TemplateSchema(
            template_id=template_id,
            inputs=summary.inputs,
            outputs=summary.outputs,
        )

    def get_definition(self, template_id: str) -> WorkflowDefinition | None:
        """Return the full workflow definition for a template."""
        return self._definitions.get(template_id)

    def get_definition_dict(self, template_id: str) -> dict[str, Any] | None:
        """Return the full workflow definition as a serializable dict."""
        defn = self._definitions.get(template_id)
        if defn is None:
            return None
        return defn.model_dump(mode="json")
