"""Marketplace category registry for pack classification.

Follows the persistence pattern from ``packs/trust_manager.py``.
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class MarketplaceCategory(BaseModel):
    """A marketplace classification category."""

    slug: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=128)
    description: str = ""
    parent_slug: str = ""


class CategoryRegistry:
    """Manage marketplace categories with state-store persistence."""

    def __init__(
        self,
        state_store: Any | None = None,
        default_categories_str: str = "",
        *,
        namespace: str = "pack_categories",
    ) -> None:
        self._state_store = state_store
        self._namespace = namespace
        self._categories: dict[str, MarketplaceCategory] = {}
        self._load()
        if not self._categories and default_categories_str.strip():
            self._seed_defaults(default_categories_str)

    def _seed_defaults(self, raw: str) -> None:
        """Create default categories from a comma-separated slug string."""
        for slug in raw.split(","):
            slug = slug.strip()
            if not slug:
                continue
            label = slug.replace("-", " ").title()
            self._categories[slug] = MarketplaceCategory(
                slug=slug,
                label=label,
                description=f"Packs in the {label} category",
            )
        self._persist()

    # -- Public API ---------------------------------------------------------

    def list_categories(self) -> list[MarketplaceCategory]:
        """Return all categories sorted by slug."""
        return [self._categories[k] for k in sorted(self._categories)]

    def get_category(self, slug: str) -> MarketplaceCategory | None:
        """Look up a category by slug."""
        return self._categories.get(slug)

    def add_category(self, cat: MarketplaceCategory) -> None:
        """Add a new category; raises ValueError if the slug already exists."""
        if cat.slug in self._categories:
            raise ValueError(f"Category '{cat.slug}' already exists")
        self._categories[cat.slug] = cat
        self._persist()
        logger.info("category_added", slug=cat.slug)

    def update_category(
        self,
        slug: str,
        *,
        label: str = "",
        description: str = "",
        parent_slug: str = "",
    ) -> MarketplaceCategory:
        """Update fields on an existing category."""
        existing = self._categories.get(slug)
        if existing is None:
            raise ValueError(f"Category '{slug}' not found")
        if label:
            existing.label = label
        if description:
            existing.description = description
        if parent_slug is not None:
            existing.parent_slug = parent_slug
        self._persist()
        return existing

    def remove_category(self, slug: str) -> None:
        """Remove a category; raises ValueError if not found."""
        if slug not in self._categories:
            raise ValueError(f"Category '{slug}' not found")
        del self._categories[slug]
        self._persist()
        logger.info("category_removed", slug=slug)

    # -- Persistence --------------------------------------------------------

    def _load(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._namespace)
        if not payload:
            return
        raw_cats = payload.get("categories", [])
        if not isinstance(raw_cats, list):
            return
        for item in raw_cats:
            if not isinstance(item, dict):
                continue
            try:
                cat = MarketplaceCategory.model_validate(item)
                self._categories[cat.slug] = cat
            except Exception:
                continue

    def _persist(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            self._namespace,
            {
                "categories": [
                    cat.model_dump(mode="json")
                    for cat in sorted(self._categories.values(), key=lambda c: c.slug)
                ]
            },
        )
