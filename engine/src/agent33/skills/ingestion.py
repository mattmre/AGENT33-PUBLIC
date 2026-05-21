"""Helpers for turning published ingestion assets into runtime skills."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote, urlparse

import yaml

from agent33.skills.definition import SkillDefinition
from agent33.skills.loader import (
    load_from_directory,
    load_from_skillmd,
    load_from_yaml,
    parse_frontmatter,
)

if TYPE_CHECKING:
    from agent33.ingestion.models import CandidateAsset

_INLINE_DEFINITION_KEY = "skill_definition"
_INLINE_MARKDOWN_KEYS = ("skill_markdown", "skill_md")
_INLINE_YAML_KEYS = ("skill_yaml",)


def skill_definition_from_candidate_asset(asset: CandidateAsset) -> SkillDefinition | None:
    """Return a runtime skill definition for a published skill asset, if possible."""
    if asset.asset_type != "skill":
        return None

    skill = _load_inline_skill_definition(asset.metadata)
    if skill is None:
        skill = _load_skill_from_source_uri(asset.source_uri)
    if skill is None:
        return None

    updates: dict[str, Any] = {}
    if not skill.provenance:
        updates["provenance"] = asset.source_uri or f"ingestion:{asset.id}"
    category = asset.metadata.get("skill_category")
    if not skill.category and isinstance(category, str):
        updates["category"] = category
    return skill.model_copy(update=updates) if updates else skill


def _load_inline_skill_definition(metadata: dict[str, Any]) -> SkillDefinition | None:
    raw_definition = metadata.get(_INLINE_DEFINITION_KEY)
    if raw_definition is not None:
        if not isinstance(raw_definition, dict):
            raise ValueError("metadata.skill_definition must be a mapping.")
        return SkillDefinition.model_validate(raw_definition)

    for key in _INLINE_MARKDOWN_KEYS:
        raw_markdown = metadata.get(key)
        if raw_markdown is None:
            continue
        if not isinstance(raw_markdown, str) or not raw_markdown.strip():
            raise ValueError(f"metadata.{key} must be a non-empty string.")
        frontmatter, body = parse_frontmatter(raw_markdown)
        frontmatter["instructions"] = body
        return SkillDefinition.model_validate(frontmatter)

    for key in _INLINE_YAML_KEYS:
        raw_yaml = metadata.get(key)
        if raw_yaml is None:
            continue
        if isinstance(raw_yaml, dict):
            return SkillDefinition.model_validate(raw_yaml)
        if not isinstance(raw_yaml, str) or not raw_yaml.strip():
            raise ValueError(f"metadata.{key} must be a non-empty string or mapping.")
        try:
            parsed = yaml.safe_load(raw_yaml)
        except yaml.YAMLError as exc:
            raise ValueError(f"metadata.{key} is not valid YAML.") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"metadata.{key} must decode to a mapping.")
        return SkillDefinition.model_validate(parsed)

    return None


def _load_skill_from_source_uri(source_uri: str | None) -> SkillDefinition | None:
    if source_uri is None or not source_uri.strip():
        return None

    path = _source_uri_to_path(source_uri)
    if path is None or not path.exists():
        return None

    try:
        if path.is_dir():
            return load_from_directory(path)
        if path.name == "SKILL.md":
            return load_from_skillmd(path)
        if path.suffix in {".yaml", ".yml"}:
            return load_from_yaml(path)
    except yaml.YAMLError as exc:
        raise ValueError(f"source_uri {source_uri!r} does not contain valid skill YAML.") from exc

    return None


def _source_uri_to_path(source_uri: str) -> Path | None:
    if _looks_like_windows_path(source_uri):
        return Path(source_uri)

    parsed = urlparse(source_uri)
    if parsed.scheme not in {"", "file"}:
        return None

    candidate = unquote(parsed.path or source_uri)
    if parsed.netloc:
        candidate = f"//{parsed.netloc}{candidate}"
    if len(candidate) >= 3 and candidate[0] == "/" and candidate[2] == ":":
        candidate = candidate[1:]
    return Path(candidate)


def _looks_like_windows_path(value: str) -> bool:
    return len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}
