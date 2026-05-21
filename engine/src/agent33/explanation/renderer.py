"""Visual page rendering helpers for diff, plan, and recap explanations."""

from __future__ import annotations

import html
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

TEMPLATE_FOLDER = "explanations"


@lru_cache(maxsize=1)
def _resolve_template_dir() -> Path | None:
    module_path = Path(__file__).resolve()
    parents = module_path.parents
    root_like = parents[3] if len(parents) > 3 else Path.cwd()
    site_pkg_like = parents[2] if len(parents) > 2 else Path.cwd()
    candidates = [
        root_like / "templates" / TEMPLATE_FOLDER,
        site_pkg_like / "templates" / TEMPLATE_FOLDER,
        Path.cwd() / "templates" / TEMPLATE_FOLDER,
        Path("/app/templates") / TEMPLATE_FOLDER,
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _safe_escape(value: str) -> str:
    return html.escape(value)


def _load_template(template_name: str) -> str:
    template_dir = _resolve_template_dir()
    if template_dir is None:
        raise FileNotFoundError("Explanation templates directory not found")

    template_dir_resolved = template_dir.resolve()
    template_path = (template_dir_resolved / template_name).resolve()
    if not template_path.is_relative_to(template_dir_resolved):
        raise ValueError(f"Template path traversal attempt: {template_name}")
    if not template_path.exists():
        raise FileNotFoundError(f"Template '{template_name}' not found at {template_path}")

    return template_path.read_text(encoding="utf-8")


def _render_template(template: str, context: dict[str, Any]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
    return rendered


def compute_diff_stats(diff_text: str) -> dict[str, int]:
    files_changed = 0
    insertions = 0
    deletions = 0

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            files_changed += 1
        elif line.startswith("+") and not line.startswith("+++"):
            insertions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1

    return {
        "files_changed": files_changed,
        "insertions": insertions,
        "deletions": deletions,
    }


def parse_markdown_headings(text: str) -> list[str]:
    pattern = re.compile(r"^##+\s+(.+)$", re.MULTILINE)
    return [match.strip() for match in pattern.findall(text)]


def render_diff_review(entity_type: str, entity_id: str, diff_text: str) -> str:
    stats = compute_diff_stats(diff_text)
    template = _load_template("diff-review.html")
    context = {
        "entity_type": _safe_escape(entity_type),
        "entity_id": _safe_escape(entity_id),
        "files_changed": stats["files_changed"],
        "insertions": stats["insertions"],
        "deletions": stats["deletions"],
        "diff_content": _safe_escape(diff_text),
    }
    return _render_template(template, context)


def render_plan_review(entity_type: str, entity_id: str, plan_text: str) -> str:
    headings = parse_markdown_headings(plan_text)
    heading_items = "\n".join(f"<li>{_safe_escape(heading)}</li>" for heading in headings)
    if not heading_items:
        heading_items = "<li>No markdown headings found</li>"

    template = _load_template("plan-review.html")
    context = {
        "entity_type": _safe_escape(entity_type),
        "entity_id": _safe_escape(entity_id),
        "section_count": len(headings),
        "heading_items": heading_items,
        "plan_content": _safe_escape(plan_text),
    }
    return _render_template(template, context)


def render_project_recap(
    entity_type: str,
    entity_id: str,
    recap_text: str,
    highlights: list[str] | None = None,
) -> str:
    highlight_values = highlights or []
    highlights_items = "\n".join(
        f"<li>{_safe_escape(item)}</li>" for item in highlight_values if item.strip()
    )
    if not highlights_items:
        highlights_items = "<li>No highlights available</li>"

    template = _load_template("project-recap.html")
    context = {
        "entity_type": _safe_escape(entity_type),
        "entity_id": _safe_escape(entity_id),
        "highlights_items": highlights_items,
        "recap_content": _safe_escape(recap_text),
    }
    return _render_template(template, context)
