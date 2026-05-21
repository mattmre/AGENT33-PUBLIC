"""Workflow template marketplace: browse, search, install, and rate templates.

Provides an in-memory marketplace for workflow templates with category-based
browsing, tag search, star ratings, and installation into the live workflow
registry.
"""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field, field_validator

from agent33.workflows.definition import WorkflowDefinition

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TemplateCategory(StrEnum):
    """Categories for workflow templates."""

    AUTOMATION = "automation"
    DATA_PIPELINE = "data-pipeline"
    RESEARCH = "research"
    REVIEW = "review"
    DEPLOYMENT = "deployment"
    CUSTOM = "custom"


class TemplateSortField(StrEnum):
    """Fields by which search results can be sorted."""

    NAME = "name"
    RATING = "rating"
    INSTALL_COUNT = "install_count"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class WorkflowTemplate(BaseModel):
    """A workflow template in the marketplace."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    category: TemplateCategory = TemplateCategory.CUSTOM
    tags: list[str] = Field(default_factory=list)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    author: str = Field(default="", max_length=128)
    rating: float = Field(default=0.0, ge=0.0, le=5.0)
    rating_count: int = Field(default=0, ge=0)
    install_count: int = Field(default=0, ge=0)
    template_definition: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    builtin: bool = Field(default=False)


class TemplateSearchQuery(BaseModel):
    """Search query for marketplace templates."""

    query: str = ""
    category: TemplateCategory | None = None
    tags: list[str] = Field(default_factory=list)
    sort_by: TemplateSortField = TemplateSortField.NAME
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class TemplateRating(BaseModel):
    """A rating for a marketplace template."""

    template_id: str
    tenant_id: str = ""
    stars: int = Field(..., ge=1, le=5)
    comment: str = Field(default="", max_length=1000)

    @field_validator("stars")
    @classmethod
    def _validate_stars(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("stars must be between 1 and 5")
        return value


class TemplateInstallResult(BaseModel):
    """Result of installing a template."""

    template_id: str
    workflow_name: str
    tenant_id: str
    installed: bool
    definition: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Marketplace Service
# ---------------------------------------------------------------------------

_MAX_TEMPLATES = 10_000


class WorkflowMarketplace:
    """In-memory workflow template marketplace.

    Thread-safe marketplace that supports template registration, search,
    installation, and ratings. Templates can be auto-discovered from YAML files
    or registered programmatically.
    """

    def __init__(self, templates_dir: str | None = None) -> None:
        self._templates_dir = Path(templates_dir) if templates_dir else None
        self._templates: dict[str, WorkflowTemplate] = {}
        self._ratings: dict[str, list[TemplateRating]] = {}
        self._installs: dict[str, set[str]] = {}  # template_id -> set of tenant_ids
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        """Number of templates in the marketplace."""
        with self._lock:
            return len(self._templates)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover_builtin_templates(self) -> int:
        """Auto-discover workflow templates from YAML files in the templates dir.

        Returns the number of templates loaded.
        """
        if self._templates_dir is None:
            logger.info("workflow_marketplace_no_dir_configured")
            return 0

        if not self._templates_dir.is_dir():
            logger.warning(
                "workflow_marketplace_dir_missing path=%s",
                str(self._templates_dir),
            )
            return 0

        loaded = 0
        for yaml_path in sorted(self._templates_dir.rglob("*.yaml")):
            try:
                defn = WorkflowDefinition.load_from_file(yaml_path)
                tags = list(defn.metadata.tags) if defn.metadata.tags else []
                author = defn.metadata.author or ""

                template = WorkflowTemplate(
                    name=defn.name,
                    description=defn.description or "",
                    category=TemplateCategory.CUSTOM,
                    tags=tags,
                    version=defn.version,
                    author=author,
                    template_definition=defn.model_dump(mode="json"),
                    builtin=True,
                )
                with self._lock:
                    if len(self._templates) >= _MAX_TEMPLATES:
                        logger.warning(
                            "workflow_marketplace_capacity_reached max=%d",
                            _MAX_TEMPLATES,
                        )
                        break
                    self._templates[template.id] = template
                loaded += 1
            except Exception:
                logger.warning(
                    "workflow_marketplace_load_failed path=%s",
                    str(yaml_path),
                    exc_info=True,
                )

        logger.info("workflow_marketplace_discovered count=%d", loaded)
        return loaded

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register_template(self, template: WorkflowTemplate) -> str:
        """Register a template in the marketplace. Returns the template ID.

        Raises ValueError if capacity is reached.
        """
        with self._lock:
            if len(self._templates) >= _MAX_TEMPLATES:
                raise ValueError(f"Marketplace capacity reached (max {_MAX_TEMPLATES} templates)")
            self._templates[template.id] = template
        logger.info(
            "workflow_template_registered",
            template_id=template.id,
            name=template.name,
        )
        return template.id

    def get_template(self, template_id: str) -> WorkflowTemplate | None:
        """Retrieve a template by ID."""
        with self._lock:
            return self._templates.get(template_id)

    def remove_template(self, template_id: str) -> bool:
        """Remove a template from the marketplace. Returns True if it existed."""
        with self._lock:
            removed = self._templates.pop(template_id, None)
            if removed is not None:
                self._ratings.pop(template_id, None)
                self._installs.pop(template_id, None)
            return removed is not None

    def list_templates(
        self,
        *,
        category: TemplateCategory | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WorkflowTemplate]:
        """List templates with optional category filter and pagination."""
        with self._lock:
            results = list(self._templates.values())

        if category is not None:
            results = [t for t in results if t.category == category]

        results.sort(key=lambda t: t.name)
        return results[offset : offset + limit]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_templates(self, query: TemplateSearchQuery) -> list[WorkflowTemplate]:
        """Search templates by query string, category, and tags."""
        with self._lock:
            candidates = list(self._templates.values())

        # Filter by category
        if query.category is not None:
            candidates = [t for t in candidates if t.category == query.category]

        # Filter by tags (all specified tags must be present)
        if query.tags:
            tag_set = set(query.tags)
            candidates = [t for t in candidates if tag_set.issubset(set(t.tags))]

        # Filter by query string (name, description, tags)
        if query.query:
            query_lower = query.query.lower()
            candidates = [
                t
                for t in candidates
                if query_lower in t.name.lower()
                or query_lower in t.description.lower()
                or any(query_lower in tag.lower() for tag in t.tags)
            ]

        # Sort
        sort_key = _sort_key_for(query.sort_by)
        reverse = query.sort_by in {
            TemplateSortField.RATING,
            TemplateSortField.INSTALL_COUNT,
            TemplateSortField.UPDATED_AT,
            TemplateSortField.CREATED_AT,
        }
        candidates.sort(key=sort_key, reverse=reverse)

        # Paginate
        return candidates[query.offset : query.offset + query.limit]

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    def install_template(
        self,
        template_id: str,
        tenant_id: str,
    ) -> TemplateInstallResult:
        """Install a template, returning the workflow definition for registration.

        Raises ValueError if the template does not exist.
        """
        with self._lock:
            template = self._templates.get(template_id)
            if template is None:
                raise ValueError(f"Template '{template_id}' not found")

            # Track installation
            self._installs.setdefault(template_id, set()).add(tenant_id)
            template.install_count = len(self._installs[template_id])

        workflow_name = template.template_definition.get("name", template.name)

        return TemplateInstallResult(
            template_id=template_id,
            workflow_name=workflow_name,
            tenant_id=tenant_id,
            installed=True,
            definition=dict(template.template_definition),
        )

    # ------------------------------------------------------------------
    # Ratings
    # ------------------------------------------------------------------

    def rate_template(self, template_id: str, rating: TemplateRating) -> None:
        """Submit a rating for a template.

        Raises ValueError if the template does not exist.
        """
        with self._lock:
            template = self._templates.get(template_id)
            if template is None:
                raise ValueError(f"Template '{template_id}' not found")

            ratings_list = self._ratings.setdefault(template_id, [])

            # Replace existing rating from same tenant (one rating per tenant)
            ratings_list[:] = [r for r in ratings_list if r.tenant_id != rating.tenant_id]
            ratings_list.append(rating)

            # Recompute average
            total_stars = sum(r.stars for r in ratings_list)
            template.rating = round(total_stars / len(ratings_list), 2)
            template.rating_count = len(ratings_list)

    def get_ratings(self, template_id: str) -> list[TemplateRating]:
        """Get all ratings for a template."""
        with self._lock:
            return list(self._ratings.get(template_id, []))

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_template_stats(self) -> dict[str, Any]:
        """Compute marketplace statistics."""
        with self._lock:
            templates = list(self._templates.values())

        total = len(templates)
        by_category: dict[str, int] = {}
        total_installs = 0
        total_ratings = 0

        for t in templates:
            by_category[t.category] = by_category.get(t.category, 0) + 1
            total_installs += t.install_count
            total_ratings += t.rating_count

        avg_rating = 0.0
        rated = [t for t in templates if t.rating_count > 0]
        if rated:
            avg_rating = round(sum(t.rating for t in rated) / len(rated), 2)

        return {
            "total_templates": total,
            "by_category": by_category,
            "total_installs": total_installs,
            "total_ratings": total_ratings,
            "average_rating": avg_rating,
        }

    # ------------------------------------------------------------------
    # Create from Workflow
    # ------------------------------------------------------------------

    def create_template_from_workflow(
        self,
        workflow_def: WorkflowDefinition,
        *,
        name: str | None = None,
        description: str | None = None,
        category: TemplateCategory = TemplateCategory.CUSTOM,
        tags: list[str] | None = None,
        author: str = "",
    ) -> str:
        """Create a marketplace template from an existing workflow definition.

        Returns the new template ID.
        """
        template_name = name or workflow_def.name
        template_description = description or workflow_def.description or ""
        template_tags = tags if tags is not None else list(workflow_def.metadata.tags or [])

        template = WorkflowTemplate(
            name=template_name,
            description=template_description,
            category=category,
            tags=template_tags,
            version=workflow_def.version,
            author=author or (workflow_def.metadata.author or ""),
            template_definition=workflow_def.model_dump(mode="json"),
        )
        return self.register_template(template)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sort_key_for(
    sort_field: TemplateSortField,
) -> Any:
    """Return a sort key function for the given sort field."""
    if sort_field == TemplateSortField.NAME:
        return lambda t: t.name.lower()
    if sort_field == TemplateSortField.RATING:
        return lambda t: t.rating
    if sort_field == TemplateSortField.INSTALL_COUNT:
        return lambda t: t.install_count
    if sort_field == TemplateSortField.CREATED_AT:
        return lambda t: t.created_at
    if sort_field == TemplateSortField.UPDATED_AT:
        return lambda t: t.updated_at
    return lambda t: t.name.lower()
