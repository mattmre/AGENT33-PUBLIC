"""Skill file parsing: SKILL.md frontmatter and YAML formats."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

from agent33.skills.definition import SkillDefinition

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n(.*)",
    re.DOTALL,
)


def _infer_skill_category(base_path: Path) -> str:
    """Infer a hierarchical category from the skill's on-disk location."""
    parts = list(base_path.parts)
    lowered = [part.lower() for part in parts]
    if "skills" not in lowered:
        return ""

    skills_index = lowered.index("skills")
    category_parts = [
        part
        for part in parts[skills_index + 1 : -1]
        if part not in {"", ".", "/", "\\"} and not part.endswith(":")
    ]
    return "/".join(category_parts)


def _finalize_loaded_skill(skill: SkillDefinition, base_path: Path) -> SkillDefinition:
    """Attach derived runtime metadata after parsing a skill file."""
    updates: dict[str, Any] = {"base_path": base_path}
    if not skill.category:
        updates["category"] = _infer_skill_category(base_path)
    finalized = skill.model_copy(update=updates)
    _validate_loaded_skill_contract(finalized, base_path)
    return finalized


def _validate_relative_resource_path(base_path: Path, resource_path: str, *, kind: str) -> None:
    if not resource_path.strip():
        raise ValueError(f"Skill {kind} path must not be empty")
    base = base_path.resolve()
    target = (base_path / resource_path).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"Skill {kind} path escapes skill directory: {resource_path}") from exc


def _validate_loaded_skill_contract(skill: SkillDefinition, base_path: Path) -> None:
    """Fail closed when a loaded skill declares unsafe or inconsistent metadata."""
    overlap = set(skill.allowed_tools) & set(skill.disallowed_tools)
    if overlap:
        names = ", ".join(sorted(overlap))
        raise ValueError(f"Skill {skill.name} both allows and blocks tools: {names}")

    if skill.scripts_dir is not None:
        _validate_relative_resource_path(base_path, skill.scripts_dir, kind="scripts_dir")
        if not (base_path / skill.scripts_dir).is_dir():
            raise ValueError(f"Skill {skill.name} scripts_dir does not exist: {skill.scripts_dir}")

    if skill.templates_dir is not None:
        _validate_relative_resource_path(base_path, skill.templates_dir, kind="templates_dir")
        if not (base_path / skill.templates_dir).is_dir():
            raise ValueError(
                f"Skill {skill.name} templates_dir does not exist: {skill.templates_dir}"
            )

    for resource_path in skill.references:
        _validate_relative_resource_path(base_path, resource_path, kind="reference")
        if not (base_path / resource_path).is_file():
            raise ValueError(f"Skill {skill.name} reference does not exist: {resource_path}")


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and markdown body from a SKILL.md file.

    Returns (metadata_dict, markdown_body).
    Raises ValueError if frontmatter cannot be parsed.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError("No YAML frontmatter found (expected --- delimiters)")

    import yaml

    raw_yaml = match.group(1)
    body = match.group(2).strip()

    try:
        metadata = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(metadata, dict):
        raise ValueError("Frontmatter must be a YAML mapping")

    return metadata, body


def load_from_skillmd(path: Path) -> SkillDefinition:
    """Parse an Anthropic-standard SKILL.md file.

    The file has YAML frontmatter (between ``---`` markers) followed by
    a markdown body.  The body becomes the ``instructions`` field.
    """
    content = path.read_text(encoding="utf-8")
    metadata, body = parse_frontmatter(content)
    metadata["instructions"] = body
    skill = SkillDefinition.model_validate(metadata)
    return _finalize_loaded_skill(skill, path.parent)


def load_from_yaml(path: Path) -> SkillDefinition:
    """Parse a structured YAML skill definition."""
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Skill YAML must be a mapping: {path}")
    skill = SkillDefinition.model_validate(raw)
    return _finalize_loaded_skill(skill, path.parent)


def load_from_directory(path: Path) -> SkillDefinition:
    """Load a skill from a directory.

    Looks for ``SKILL.md`` first, then ``skill.yaml`` / ``skill.yml``.
    Discovers conventional subdirectories (scripts/, templates/).
    """
    skillmd = path / "SKILL.md"
    if skillmd.is_file():
        skill = load_from_skillmd(skillmd)
    else:
        for candidate in ("skill.yaml", "skill.yml"):
            yaml_path = path / candidate
            if yaml_path.is_file():
                skill = load_from_yaml(yaml_path)
                break
        else:
            raise FileNotFoundError(f"No SKILL.md or skill.yaml found in {path}")

    # Discover conventional artifact directories
    scripts = path / "scripts"
    if scripts.is_dir() and skill.scripts_dir is None:
        skill = skill.model_copy(update={"scripts_dir": "scripts"})

    templates = path / "templates"
    if templates.is_dir() and skill.templates_dir is None:
        skill = skill.model_copy(update={"templates_dir": "templates"})

    return skill
