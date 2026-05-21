"""Operator-friendly skill authoring endpoints."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.config import settings
from agent33.security.permissions import require_scope
from agent33.skills.definition import (
    SkillDefinition,
    SkillExecutionContext,
    SkillInvocationMode,
)
from agent33.skills.lineage import SkillLineageEvent, SkillPromotionRequest
from agent33.skills.loader import load_from_skillmd

if TYPE_CHECKING:
    from agent33.skills.registry import SkillRegistry

router = APIRouter(prefix="/v1/skills/authoring", tags=["skill-authoring"])

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


class SkillDraftRequest(BaseModel):
    """Plain-language skill authoring request."""

    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(..., min_length=1, max_length=500)
    use_case: str = Field(..., min_length=1, max_length=1000)
    workflow_steps: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    approval_required_for: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    category: str = "operator-authored"
    author: str = "operator"
    autonomy_level: str | None = "supervised"
    invocation_mode: SkillInvocationMode = SkillInvocationMode.BOTH
    execution_context: SkillExecutionContext = SkillExecutionContext.INLINE
    install: bool = False
    overwrite: bool = False


class SkillDraftResponse(BaseModel):
    """Skill authoring response with generated artifact preview."""

    skill: dict[str, Any]
    markdown: str
    installed: bool
    path: str | None = None
    warnings: list[str] = Field(default_factory=list)


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        raise HTTPException(status_code=422, detail="Skill name must contain letters or numbers")
    return slug[:64]


def _clean_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        cleaned.append(item)
    return cleaned


def _build_instructions(body: SkillDraftRequest) -> str:
    steps = _clean_list(body.workflow_steps)
    success = _clean_list(body.success_criteria)
    approvals = _clean_list(body.approval_required_for)

    lines = [
        f"# {body.name.strip()}",
        "",
        "## Purpose",
        body.use_case.strip(),
        "",
        "## Operator workflow",
    ]
    if steps:
        lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    else:
        lines.append("1. Confirm the user goal and collect any missing context.")
        lines.append("2. Execute the safest useful action with the allowed tools.")
        lines.append("3. Summarize the result and any follow-up needed.")

    lines.extend(["", "## Safety guardrails"])
    if approvals:
        lines.append("Ask for approval before:")
        lines.extend(f"- {item}" for item in approvals)
    else:
        lines.append("Keep destructive or irreversible actions supervised by default.")

    lines.extend(["", "## Done when"])
    if success:
        lines.extend(f"- {item}" for item in success)
    else:
        lines.append("- The operator can understand what changed and what remains.")

    return "\n".join(lines).strip()


def _build_skill_definition(slug: str, body: SkillDraftRequest) -> SkillDefinition:
    return SkillDefinition(
        name=slug,
        description=body.description.strip(),
        instructions=_build_instructions(body),
        allowed_tools=_clean_list(body.allowed_tools),
        approval_required_for=_clean_list(body.approval_required_for),
        tags=_clean_list(body.tags),
        category=body.category.strip() or "operator-authored",
        provenance="operator-wizard",
        author=body.author.strip() or "operator",
        autonomy_level=body.autonomy_level,
        invocation_mode=body.invocation_mode,
        execution_context=body.execution_context,
        command_name=slug,
        command_help=body.description.strip()[:200],
    )


def _render_skill_markdown(skill: SkillDefinition) -> str:
    metadata = skill.model_dump(
        mode="json",
        exclude={
            "instructions",
            "supporting_files",
            "scripts_dir",
            "templates_dir",
            "references",
            "tool_parameter_defaults",
            "disallowed_tools",
            "dependencies",
        },
        exclude_none=True,
    )
    metadata = {key: value for key, value in metadata.items() if value not in ("", [], {})}
    frontmatter = yaml.safe_dump(metadata, sort_keys=False).strip()
    return f"---\n{frontmatter}\n---\n\n{skill.instructions}\n"


def _install_skill(markdown: str, slug: str, overwrite: bool, request: Request) -> str:
    skills_dir = Path(settings.skill_definitions_dir).resolve()
    target_dir = (skills_dir / "operator-authored" / slug).resolve()
    try:
        target_dir.relative_to(skills_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Resolved skill path escaped the skills directory",
        ) from exc

    target_file = target_dir / "SKILL.md"
    if target_file.exists() and not overwrite:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Skill '{slug}' already exists. Enable overwrite to replace it.",
        )

    target_dir.mkdir(parents=True, exist_ok=True)
    target_file.write_text(markdown, encoding="utf-8")

    skill = load_from_skillmd(target_file)
    registry = getattr(request.app.state, "skill_registry", None)
    if registry is not None:
        registry.register(skill)
    return str(target_file)


def _get_skill_registry(request: Request) -> SkillRegistry:
    registry = getattr(request.app.state, "skill_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Skill registry not initialized",
        )
    return cast("SkillRegistry", registry)


@router.post("/drafts", dependencies=[require_scope("agents:write")])
async def create_skill_draft(body: SkillDraftRequest, request: Request) -> dict[str, Any]:
    """Generate a SKILL.md draft and optionally install it into the runtime registry."""

    slug = _slugify(body.name)
    skill = _build_skill_definition(slug, body)
    markdown = _render_skill_markdown(skill)
    warnings: list[str] = []
    installed_path: str | None = None

    if not skill.allowed_tools:
        warnings.append("No tools were selected; this skill will provide guidance only.")
    if body.install:
        installed_path = _install_skill(markdown, slug, body.overwrite, request)

    return SkillDraftResponse(
        skill=skill.model_dump(mode="json"),
        markdown=markdown,
        installed=body.install,
        path=installed_path,
        warnings=warnings,
    ).model_dump()


@router.post(
    "/{name}/promotion",
    response_model=SkillLineageEvent,
    dependencies=[require_scope("agents:write")],
)
async def promote_skill(
    name: str,
    body: SkillPromotionRequest,
    request: Request,
) -> SkillLineageEvent:
    """Promote or demote a registered skill while recording audit evidence."""

    registry = _get_skill_registry(request)
    event = registry.promote(name, body)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{name}' is not registered",
        )
    return event


@router.get(
    "/{name}/lineage",
    response_model=list[SkillLineageEvent],
    dependencies=[require_scope("agents:read")],
)
async def get_skill_lineage(name: str, request: Request) -> list[SkillLineageEvent]:
    """Return lifecycle audit events for a registered skill."""

    registry = _get_skill_registry(request)
    if registry.get(name) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Skill '{name}' is not registered",
        )
    return registry.lineage(name)
