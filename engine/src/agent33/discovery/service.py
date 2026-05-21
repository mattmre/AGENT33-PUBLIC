"""Shared discovery service for tools, skills, and workflows.

This module provides deterministic lexical discovery primitives without
changing runtime tool exposure. It sits above the existing registries and
template catalog so the same behavior can be reused by FastAPI routes and
the MCP server.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from agent33.skills.definition import SkillDefinition, SkillStatus
from agent33.skills.matching import _tokenize

if TYPE_CHECKING:
    from pathlib import Path

    from agent33.packs.registry import PackRegistry
    from agent33.skills.registry import SkillRegistry
    from agent33.tools.registry import ToolRegistry
    from agent33.workflows.definition import WorkflowDefinition
    from agent33.workflows.template_catalog import TemplateCatalog

logger = logging.getLogger(__name__)


class ToolDiscoveryMatch(BaseModel):
    """Ranked tool discovery result."""

    name: str
    description: str = ""
    score: float
    status: str = "active"
    version: str = ""
    tags: list[str] = Field(default_factory=list)


class SkillDiscoveryMatch(BaseModel):
    """Ranked skill discovery result."""

    name: str
    description: str = ""
    score: float
    version: str = ""
    tags: list[str] = Field(default_factory=list)
    pack: str | None = None


class WorkflowResolutionMatch(BaseModel):
    """Ranked workflow resolution result."""

    name: str
    description: str = ""
    score: float
    source: Literal["runtime", "template", "skill"]
    version: str = ""
    tags: list[str] = Field(default_factory=list)
    source_path: str = ""
    pack: str | None = None


class ToolDiscoveryResponse(BaseModel):
    """Response model for tool discovery."""

    query: str
    matches: list[ToolDiscoveryMatch] = Field(default_factory=list)


class SkillDiscoveryResponse(BaseModel):
    """Response model for skill discovery."""

    query: str
    matches: list[SkillDiscoveryMatch] = Field(default_factory=list)


class WorkflowResolutionResponse(BaseModel):
    """Response model for workflow resolution."""

    query: str
    matches: list[WorkflowResolutionMatch] = Field(default_factory=list)


class DiscoveryService:
    """Deterministic discovery over the live runtime registries."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry | None = None,
        skill_registry: SkillRegistry | None = None,
        pack_registry: PackRegistry | None = None,
        workflow_registry: dict[str, WorkflowDefinition] | None = None,
        template_catalog: TemplateCatalog | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._skill_registry = skill_registry
        self._pack_registry = pack_registry
        self._workflow_registry = workflow_registry
        self._template_catalog = template_catalog

    def discover_tools(self, query: str, *, limit: int = 10) -> list[ToolDiscoveryMatch]:
        """Return ranked tools relevant to a task description."""
        if self._tool_registry is None:
            return []

        matches: list[ToolDiscoveryMatch] = []
        for tool in self._tool_registry.list_all():
            name = getattr(tool, "name", "")
            description = getattr(tool, "description", "")
            entry = self._tool_registry.get_entry(name)
            status = getattr(getattr(entry, "status", None), "value", "active")
            if status == "blocked":
                continue

            tags = list(getattr(entry, "tags", []) or [])
            version = getattr(entry, "version", "") or ""
            score = _score_candidate(query, name, description, tags)
            if score <= 0:
                continue
            if status == "deprecated":
                score *= 0.85

            matches.append(
                ToolDiscoveryMatch(
                    name=name,
                    description=description,
                    score=round(score, 4),
                    status=status,
                    version=version,
                    tags=tags,
                )
            )

        matches.sort(key=lambda match: (-match.score, match.name))
        return matches[: max(limit, 1)]

    def discover_skills(
        self,
        query: str,
        *,
        limit: int = 10,
        tenant_id: str | None = None,
    ) -> list[SkillDiscoveryMatch]:
        """Return ranked skills relevant to a task description."""
        matches = [
            SkillDiscoveryMatch(
                name=canonical_name,
                description=skill.description,
                score=score,
                version=skill.version,
                tags=list(skill.tags),
                pack=pack_name,
            )
            for skill, canonical_name, pack_name, score in self._rank_skills(
                query,
                tenant_id=tenant_id,
            )
        ]
        return matches[: max(limit, 1)]

    def resolve_workflow(
        self,
        query: str,
        *,
        limit: int = 10,
        tenant_id: str | None = None,
    ) -> list[WorkflowResolutionMatch]:
        """Return ranked runtime workflows and templates relevant to a query."""
        matches: list[WorkflowResolutionMatch] = []

        for workflow in (self._workflow_registry or {}).values():
            tags = list(getattr(getattr(workflow, "metadata", None), "tags", []) or [])
            score = _score_candidate(
                query,
                workflow.name,
                workflow.description or "",
                tags,
            )
            if score <= 0:
                continue
            score += 0.5
            matches.append(
                WorkflowResolutionMatch(
                    name=workflow.name,
                    description=workflow.description or "",
                    score=round(score, 4),
                    source="runtime",
                    version=workflow.version,
                    tags=tags,
                )
            )

        if self._template_catalog is not None:
            for template in self._template_catalog.list_templates():
                score = _score_candidate(
                    query,
                    template.name,
                    template.description or "",
                    [*template.tags, template.source_path],
                )
                if score <= 0:
                    continue
                matches.append(
                    WorkflowResolutionMatch(
                        name=template.name,
                        description=template.description or "",
                        score=round(score, 4),
                        source="template",
                        version=template.version,
                        tags=list(template.tags),
                        source_path=template.source_path,
                    )
                )

        for skill, canonical_name, pack_name, score in self._rank_skills(
            query,
            tenant_id=tenant_id,
        ):
            matches.append(
                WorkflowResolutionMatch(
                    name=canonical_name,
                    description=skill.description,
                    score=score,
                    source="skill",
                    version=skill.version,
                    tags=list(skill.tags),
                    source_path=_skill_source_path(skill.base_path),
                    pack=pack_name,
                )
            )

        source_priority = {"runtime": 0, "skill": 1, "template": 2}
        matches.sort(
            key=lambda match: (-match.score, source_priority.get(match.source, 99), match.name)
        )
        return matches[: max(limit, 1)]

    def _rank_skills(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
    ) -> list[tuple[SkillDefinition, str, str | None, float]]:
        """Return ranked visible skills with canonical names and scores."""
        if self._skill_registry is None:
            return []

        deduped: dict[str, tuple[SkillDefinition, str, str | None, float]] = {}
        for skill in self._skill_registry.list_all():
            if skill.status == SkillStatus.DEPRECATED:
                continue

            pack_name = self._resolve_skill_pack(skill)
            if (
                pack_name is not None
                and tenant_id is not None
                and (
                    self._pack_registry is None
                    or not self._pack_registry.is_enabled(pack_name, tenant_id)
                )
            ):
                continue

            canonical_name = self._canonical_skill_name(skill, pack_name)
            if canonical_name != skill.name and "/" in skill.name:
                continue

            score = _score_skill_candidate(
                query,
                canonical_name=canonical_name,
                description=skill.description,
                tags=[*skill.tags, *skill.allowed_tools],
                instructions=skill.instructions,
                category_terms=_skill_category_terms(skill, pack_name),
            )
            if score <= 0:
                continue

            ranked = (skill, canonical_name, pack_name, round(score, 4))
            existing = deduped.get(canonical_name)
            if existing is None or ranked[3] > existing[3]:
                deduped[canonical_name] = ranked

        return sorted(deduped.values(), key=lambda item: (-item[3], item[1]))

    def _resolve_skill_pack(self, skill: SkillDefinition) -> str | None:
        """Return the owning pack name for a skill, if any."""
        if self._pack_registry is None:
            return None

        for pack in self._pack_registry.list_installed():
            if skill.name in pack.loaded_skill_names:
                return pack.name

            if skill.base_path is None:
                continue

            try:
                skill.base_path.resolve().relative_to(pack.pack_dir.resolve())
            except ValueError:
                continue
            return pack.name

        return None

    def _canonical_skill_name(self, skill: SkillDefinition, pack_name: str | None) -> str:
        """Prefer a visible bare alias over a pack-qualified skill name."""
        if pack_name is None or "/" not in skill.name or self._skill_registry is None:
            return skill.name

        alias = skill.name.split("/", 1)[1]
        alias_skill = self._skill_registry.get(alias)
        if alias_skill is None:
            return skill.name

        if self._resolve_skill_pack(alias_skill) == pack_name:
            return alias

        return skill.name


def _score_candidate(query: str, primary_name: str, description: str, tags: list[str]) -> float:
    """Return a deterministic lexical relevance score for a candidate."""
    query_lower = query.strip().lower()
    if not query_lower:
        return 0.0

    query_tokens = _tokenize(query)
    primary_tokens = set(_tokenize(primary_name))
    combined_text = " ".join(part for part in (primary_name, description, " ".join(tags)) if part)
    combined_lower = combined_text.lower()
    combined_tokens = set(_tokenize(combined_text))

    if not query_tokens and query_lower not in combined_lower:
        return 0.0

    score = 0.0
    if primary_name.lower() == query_lower:
        score += 12.0
    elif primary_name.lower().startswith(query_lower):
        score += 8.0
    elif query_lower in primary_name.lower():
        score += 5.0
    elif query_lower in combined_lower:
        score += 3.0

    covered = 0
    for token in query_tokens:
        if token in combined_tokens:
            covered += 1
            score += 1.5 if token in primary_tokens else 1.0

    if covered == 0 and query_lower not in combined_lower:
        return 0.0

    if query_tokens:
        score += covered / len(query_tokens)

    return score


def _score_skill_candidate(
    query: str,
    *,
    canonical_name: str,
    description: str,
    tags: list[str],
    instructions: str,
    category_terms: list[str],
) -> float:
    """Return a weighted lexical score for skills using richer content signals."""
    score = _score_candidate(query, canonical_name, description, [*tags, *category_terms])
    if score <= 0:
        score = _score_secondary_text(query, " ".join([*tags, *category_terms]))
        if score <= 0:
            return 0.0

    instruction_excerpt = instructions[:600]
    if instruction_excerpt:
        score += min(_score_secondary_text(query, instruction_excerpt) * 0.4, 3.0)

    return score


def _score_secondary_text(query: str, text: str) -> float:
    """Return a lower-weight lexical score for supporting text sections."""
    query_lower = query.strip().lower()
    if not query_lower or not text.strip():
        return 0.0

    text_lower = text.lower()
    text_tokens = set(_tokenize(text))
    query_tokens = _tokenize(query)

    score = 0.0
    if query_lower in text_lower:
        score += 2.0

    covered = 0
    for token in query_tokens:
        if token in text_tokens:
            covered += 1
            score += 0.6

    if covered == 0 and query_lower not in text_lower:
        return 0.0

    if query_tokens:
        score += covered / len(query_tokens)

    return score


def _skill_category_terms(skill: SkillDefinition, pack_name: str | None) -> list[str]:
    """Build extra searchable terms from pack and path metadata."""
    terms: list[str] = []
    if pack_name:
        terms.append(pack_name)

    if skill.base_path is not None:
        terms.extend(part for part in skill.base_path.parts if part not in {"."})

    return terms


def _skill_source_path(base_path: Path | None) -> str:
    """Return a non-sensitive logical path for a skill when available."""
    if base_path is None:
        return ""

    try:
        normalized_parts = [
            part
            for part in base_path.parts
            if part not in {"", ".", "/", "\\"} and not part.endswith(":")
        ]
    except Exception:
        return getattr(base_path, "name", "") or ""

    lowered_parts = [part.lower() for part in normalized_parts]
    if "skills" in lowered_parts:
        skills_index = lowered_parts.index("skills")
        return "/".join(normalized_parts[skills_index:])

    return normalized_parts[-1] if normalized_parts else ""
