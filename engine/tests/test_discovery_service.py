"""Tests for Phase 46A discovery and workflow resolution primitives."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent33.discovery.service import DiscoveryService
from agent33.packs.registry import PackRegistry
from agent33.skills.definition import SkillDefinition
from agent33.skills.registry import SkillRegistry
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.registry import ToolRegistry
from agent33.tools.registry_entry import ToolRegistryEntry, ToolStatus
from agent33.workflows.definition import WorkflowDefinition
from agent33.workflows.template_catalog import TemplateCatalog

if TYPE_CHECKING:
    from pathlib import Path


class _StubTool:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.ok("ok")


def _write_pack(base: Path, *, name: str = "alpha", skills: list[str] | None = None) -> Path:
    pack_dir = base / name
    pack_dir.mkdir(parents=True, exist_ok=True)
    skill_names = skills or ["skill-a"]
    skills_yaml = "\n".join(
        f"  - name: {skill}\n    path: skills/{skill}" for skill in skill_names
    )
    (pack_dir / "PACK.yaml").write_text(
        "\n".join(
            [
                f'name: "{name}"',
                'version: "1.0.0"',
                f'description: "Pack {name}"',
                'author: "tester"',
                "skills:",
                skills_yaml,
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    for skill_name in skill_names:
        skill_dir = pack_dir / "skills" / skill_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "\n".join(
                [
                    "---",
                    f"name: {skill_name}",
                    "version: 1.0.0",
                    f"description: Skill {skill_name} from {name}",
                    "---",
                    f"# {skill_name}",
                    "Use this skill for safe deployment.",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    return pack_dir


def _write_template(base_dir: Path, filename: str, name: str, tag: str) -> None:
    template_dir = base_dir / "improvement-cycle"
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / filename).write_text(
        f"""\
name: {name}
version: 1.0.0
description: A workflow for {name}.
steps:
  - id: validate
    action: validate
    inputs:
      data: session_id
      expression: "'data'"
metadata:
  author: test
  tags:
    - {tag}
""",
        encoding="utf-8",
    )


def _workflow_definition(name: str, tag: str) -> WorkflowDefinition:
    return WorkflowDefinition.model_validate(
        {
            "name": name,
            "version": "1.0.0",
            "description": f"A runtime workflow for {name}",
            "steps": [{"id": "validate", "action": "validate", "inputs": {"data": "x"}}],
            "metadata": {"tags": [tag]},
        }
    )


class TestDiscoveryService:
    def test_discover_tools_filters_blocked_and_ranks_matches(self) -> None:
        registry = ToolRegistry()
        shell = _StubTool("shell", "Run shell commands")
        browser = _StubTool("browser", "Open web pages")
        registry.register_with_entry(
            shell,
            ToolRegistryEntry(
                tool_id="shell",
                name="shell",
                version="1.0.0",
                description="Run shell commands",
                tags=["system", "cli"],
                status=ToolStatus.ACTIVE,
            ),
        )
        registry.register_with_entry(
            browser,
            ToolRegistryEntry(
                tool_id="browser",
                name="browser",
                version="1.0.0",
                description="Open web pages",
                tags=["web"],
                status=ToolStatus.BLOCKED,
            ),
        )

        service = DiscoveryService(tool_registry=registry)
        matches = service.discover_tools("run shell command", limit=5)

        assert [match.name for match in matches] == ["shell"]
        assert matches[0].status == "active"
        assert matches[0].score > 0

    def test_discover_skills_hides_pack_skills_for_disabled_tenant(self, tmp_path: Path) -> None:
        skill_registry = SkillRegistry()
        skill_registry.register(
            SkillDefinition(
                name="git-triage",
                description="Triage repository issues",
                tags=["git", "triage"],
            )
        )
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="alpha", skills=["deploy-safely"])
        pack_registry = PackRegistry(packs_dir=packs_dir, skill_registry=skill_registry)
        assert pack_registry.discover() == 1

        service = DiscoveryService(skill_registry=skill_registry, pack_registry=pack_registry)

        disabled_matches = service.discover_skills(
            "deploy safely to production",
            tenant_id="tenant-a",
        )
        assert [match.name for match in disabled_matches] == []

        pack_registry.enable("alpha", "tenant-a")
        enabled_matches = service.discover_skills(
            "deploy safely to production",
            tenant_id="tenant-a",
        )
        assert [match.name for match in enabled_matches] == ["deploy-safely"]
        assert enabled_matches[0].pack == "alpha"

    def test_discover_skills_scores_instruction_content_and_path_terms(
        self, tmp_path: Path
    ) -> None:
        skill_registry = SkillRegistry()
        skill_dir = tmp_path / "skills" / "incident" / "runbook"
        skill_dir.mkdir(parents=True)
        skill_registry.register(
            SkillDefinition(
                name="incident-runbook",
                description="Handle incidents",
                instructions="Follow the pager escalation policy and on-call runbook carefully.",
                tags=["operations"],
                base_path=skill_dir,
            )
        )

        service = DiscoveryService(skill_registry=skill_registry)
        matches = service.discover_skills("pager escalation runbook", limit=5)

        assert [match.name for match in matches] == ["incident-runbook"]
        assert matches[0].score > 0

    def test_resolve_workflow_prefers_runtime_exact_match_over_template(
        self, tmp_path: Path
    ) -> None:
        workflows_dir = tmp_path / "core" / "workflows"
        _write_template(workflows_dir, "release.workflow.yaml", "release", "shipping")
        _write_template(workflows_dir, "retro.workflow.yaml", "retrospective", "retrospective")
        template_catalog = TemplateCatalog(workflows_dir)
        assert template_catalog.refresh() == 2

        service = DiscoveryService(
            workflow_registry={
                "release": _workflow_definition("release", "shipping"),
                "quality-check": _workflow_definition("quality-check", "quality"),
            },
            template_catalog=template_catalog,
        )

        matches = service.resolve_workflow("release", limit=5)

        assert len(matches) >= 2
        assert matches[0].name == "release"
        assert matches[0].source == "runtime"
        assert any(match.source == "template" and match.name == "release" for match in matches)

    def test_resolve_workflow_includes_skill_matches_with_tenant_filter(
        self, tmp_path: Path
    ) -> None:
        skill_registry = SkillRegistry()
        packs_dir = tmp_path / "packs"
        packs_dir.mkdir()
        _write_pack(packs_dir, name="alpha", skills=["deploy-safely"])
        pack_registry = PackRegistry(packs_dir=packs_dir, skill_registry=skill_registry)
        assert pack_registry.discover() == 1

        service = DiscoveryService(
            skill_registry=skill_registry,
            pack_registry=pack_registry,
            workflow_registry={"quality-check": _workflow_definition("quality-check", "quality")},
        )

        disabled_matches = service.resolve_workflow(
            "deploy safely to production",
            limit=5,
            tenant_id="tenant-a",
        )
        assert all(match.source != "skill" for match in disabled_matches)

        pack_registry.enable("alpha", "tenant-a")
        enabled_matches = service.resolve_workflow(
            "deploy safely to production",
            limit=5,
            tenant_id="tenant-a",
        )

        skill_matches = [match for match in enabled_matches if match.source == "skill"]
        assert skill_matches
        assert skill_matches[0].name == "deploy-safely"
        assert skill_matches[0].pack == "alpha"
        assert skill_matches[0].source_path == "skills/deploy-safely"

    def test_resolve_workflow_skill_source_path_is_logical_not_absolute(
        self, tmp_path: Path
    ) -> None:
        skill_registry = SkillRegistry()
        skill_dir = tmp_path / "Users" / "tester" / "skills" / "incident" / "runbook"
        skill_dir.mkdir(parents=True)
        skill_registry.register(
            SkillDefinition(
                name="incident-runbook",
                description="Handle incidents",
                instructions="Follow the on-call runbook carefully.",
                tags=["operations"],
                base_path=skill_dir,
            )
        )

        service = DiscoveryService(skill_registry=skill_registry)
        matches = service.resolve_workflow("on-call runbook", limit=5)

        skill_matches = [match for match in matches if match.source == "skill"]
        assert skill_matches
        assert skill_matches[0].source_path == "skills/incident/runbook"
        assert "Users" not in skill_matches[0].source_path
        assert ":" not in skill_matches[0].source_path
