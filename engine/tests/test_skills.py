"""Tests for the skills/plugin system.

Tests cover: SkillDefinition model, SKILL.md frontmatter parsing,
YAML loading, SkillRegistry discovery/CRUD/search, SkillInjector
prompt building and tool context resolution, and agent runtime
integration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent33.skills.definition import (
    SkillDefinition,
    SkillDependency,
    SkillExecutionContext,
    SkillInvocationMode,
    SkillStatus,
)

# ═══════════════════════════════════════════════════════════════════════
# SkillDefinition Model Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSkillDefinition:
    """Test the SkillDefinition Pydantic model."""

    def test_minimal_skill(self) -> None:
        skill = SkillDefinition(name="test")
        assert skill.name == "test"
        assert skill.version == "1.0.0"
        assert skill.description == ""
        assert skill.instructions == ""
        assert skill.allowed_tools == []
        assert skill.status == SkillStatus.ACTIVE
        assert skill.invocation_mode == SkillInvocationMode.BOTH
        assert skill.execution_context == SkillExecutionContext.INLINE

    def test_full_skill(self) -> None:
        skill = SkillDefinition(
            name="kubernetes-deploy",
            version="2.0.0",
            description="Deploy K8s workloads safely",
            instructions="# Deploy\nStep 1: ...",
            allowed_tools=["shell", "file_ops"],
            disallowed_tools=["browser"],
            approval_required_for=["kubectl apply", "kubectl delete"],
            tags=["devops", "kubernetes"],
            author="agent-33",
            status=SkillStatus.EXPERIMENTAL,
            invocation_mode=SkillInvocationMode.USER_ONLY,
            execution_context=SkillExecutionContext.FORK,
            autonomy_level="supervised",
            dependencies=[
                SkillDependency(name="shell", kind="tool"),
            ],
        )
        assert skill.name == "kubernetes-deploy"
        assert skill.version == "2.0.0"
        assert len(skill.allowed_tools) == 2
        assert len(skill.approval_required_for) == 2
        assert skill.dependencies[0].kind == "tool"

    def test_name_validation(self) -> None:
        # Name too short
        with pytest.raises(ValueError):
            SkillDefinition(name="")

    def test_serialization_roundtrip(self) -> None:
        skill = SkillDefinition(
            name="test",
            description="A test skill",
            allowed_tools=["shell"],
            tags=["test"],
        )
        data = skill.model_dump(mode="json")
        restored = SkillDefinition.model_validate(data)
        assert restored.name == skill.name
        assert restored.allowed_tools == skill.allowed_tools

    def test_base_path_excluded_from_dump(self) -> None:
        skill = SkillDefinition(
            name="test",
            base_path=Path("/tmp/skills/test"),
        )
        data = skill.model_dump(mode="json")
        assert "base_path" not in data


# ═══════════════════════════════════════════════════════════════════════
# Frontmatter Parsing Tests
# ═══════════════════════════════════════════════════════════════════════


class TestParseFrontmatter:
    """Test SKILL.md frontmatter parsing."""

    def test_valid_frontmatter(self) -> None:
        from agent33.skills.loader import parse_frontmatter

        content = """---
name: test-skill
version: 1.0.0
description: A test skill
tags:
  - testing
---

# Instructions

Do the thing.
"""
        meta, body = parse_frontmatter(content)
        assert meta["name"] == "test-skill"
        assert meta["version"] == "1.0.0"
        assert meta["tags"] == ["testing"]
        assert "# Instructions" in body
        assert "Do the thing." in body

    def test_no_frontmatter(self) -> None:
        from agent33.skills.loader import parse_frontmatter

        with pytest.raises(ValueError, match="No YAML frontmatter"):
            parse_frontmatter("Just some markdown")

    def test_invalid_yaml(self) -> None:
        from agent33.skills.loader import parse_frontmatter

        content = """---
invalid: yaml: content: [broken
---

Body text.
"""
        with pytest.raises(ValueError, match="Invalid YAML"):
            parse_frontmatter(content)

    def test_non_mapping_frontmatter(self) -> None:
        from agent33.skills.loader import parse_frontmatter

        content = """---
- just
- a
- list
---

Body.
"""
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            parse_frontmatter(content)


# ═══════════════════════════════════════════════════════════════════════
# Skill Loader Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSkillLoader:
    """Test loading skills from files."""

    def test_load_from_skillmd(self, tmp_path: Path) -> None:
        from agent33.skills.loader import load_from_skillmd

        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            """---
name: example
version: 1.0.0
description: Example skill
allowed_tools:
  - shell
tags:
  - example
---

# Example Skill

This is the instructions body.
""",
            encoding="utf-8",
        )
        skill = load_from_skillmd(skill_file)
        assert skill.name == "example"
        assert skill.allowed_tools == ["shell"]
        assert "# Example Skill" in skill.instructions
        assert skill.base_path == tmp_path

    def test_load_from_yaml(self, tmp_path: Path) -> None:
        from agent33.skills.loader import load_from_yaml

        skill_file = tmp_path / "skill.yaml"
        skill_file.write_text(
            """name: yaml-skill
version: 2.0.0
description: A YAML skill
instructions: |
  Do the thing.
allowed_tools:
  - file_ops
tags:
  - yaml
""",
            encoding="utf-8",
        )
        skill = load_from_yaml(skill_file)
        assert skill.name == "yaml-skill"
        assert skill.version == "2.0.0"
        assert "Do the thing." in skill.instructions

    def test_load_from_directory_skillmd(self, tmp_path: Path) -> None:
        from agent33.skills.loader import load_from_directory

        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            """---
name: dir-skill
description: Directory skill
---

Instructions here.
""",
            encoding="utf-8",
        )
        # Add conventional directories
        (skill_dir / "scripts").mkdir()
        (skill_dir / "templates").mkdir()

        skill = load_from_directory(skill_dir)
        assert skill.name == "dir-skill"
        assert skill.scripts_dir == "scripts"
        assert skill.templates_dir == "templates"

    def test_load_from_directory_yaml(self, tmp_path: Path) -> None:
        from agent33.skills.loader import load_from_directory

        skill_dir = tmp_path / "yaml-skill"
        skill_dir.mkdir()
        (skill_dir / "skill.yaml").write_text(
            """name: yaml-dir
description: YAML directory skill
""",
            encoding="utf-8",
        )
        skill = load_from_directory(skill_dir)
        assert skill.name == "yaml-dir"

    def test_load_from_directory_not_found(self, tmp_path: Path) -> None:
        from agent33.skills.loader import load_from_directory

        skill_dir = tmp_path / "empty"
        skill_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="No SKILL.md or skill.yaml"):
            load_from_directory(skill_dir)

    def test_load_rejects_reference_path_escape(self, tmp_path: Path) -> None:
        from agent33.skills.loader import load_from_yaml

        skill_file = tmp_path / "skill.yaml"
        skill_file.write_text(
            """name: unsafe-reference
references:
  - ../secret.txt
""",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="reference path escapes"):
            load_from_yaml(skill_file)

    def test_load_rejects_missing_declared_scripts_dir(self, tmp_path: Path) -> None:
        from agent33.skills.loader import load_from_yaml

        skill_file = tmp_path / "skill.yaml"
        skill_file.write_text(
            """name: missing-script-dir
scripts_dir: scripts
""",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="scripts_dir does not exist"):
            load_from_yaml(skill_file)

    def test_load_rejects_conflicting_tool_contract(self, tmp_path: Path) -> None:
        from agent33.skills.loader import load_from_yaml

        skill_file = tmp_path / "skill.yaml"
        skill_file.write_text(
            """name: conflicting-tools
allowed_tools:
  - shell
disallowed_tools:
  - shell
""",
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="both allows and blocks"):
            load_from_yaml(skill_file)


# ═══════════════════════════════════════════════════════════════════════
# Skill Registry Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSkillRegistry:
    """Test SkillRegistry CRUD and discovery."""

    def test_register_and_get(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        skill = SkillDefinition(name="test", description="Test skill")
        registry.register(skill)
        assert registry.get("test") is skill
        assert registry.count == 1

    def test_get_missing(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        assert registry.get("nonexistent") is None

    def test_remove(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        skill = SkillDefinition(name="test")
        registry.register(skill)
        assert registry.remove("test") is True
        assert registry.get("test") is None
        assert registry.remove("test") is False

    def test_list_all_sorted(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(SkillDefinition(name="charlie"))
        registry.register(SkillDefinition(name="alpha"))
        registry.register(SkillDefinition(name="bravo"))
        skills = registry.list_all()
        assert [s.name for s in skills] == ["alpha", "bravo", "charlie"]

    def test_replace_existing(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(SkillDefinition(name="test", version="1.0.0"))
        registry.register(SkillDefinition(name="test", version="2.0.0"))
        skill = registry.get("test")
        assert skill is not None
        assert skill.version == "2.0.0"
        assert registry.count == 1

    def test_register_notifies_change_listeners(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        observed: list[str] = []

        registry.add_change_listener(lambda: observed.append("changed"))
        registry.register(SkillDefinition(name="test"))

        assert observed == ["changed"]

    def test_find_by_tag(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(SkillDefinition(name="a", tags=["devops", "k8s"]))
        registry.register(SkillDefinition(name="b", tags=["code"]))
        registry.register(SkillDefinition(name="c", tags=["devops"]))
        results = registry.find_by_tag("devops")
        assert len(results) == 2
        assert {s.name for s in results} == {"a", "c"}

    def test_find_by_tool(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(SkillDefinition(name="a", allowed_tools=["shell"]))
        registry.register(SkillDefinition(name="b", allowed_tools=["file_ops"]))
        results = registry.find_by_tool("shell")
        assert len(results) == 1
        assert results[0].name == "a"

    def test_search(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(SkillDefinition(name="deploy", description="Deploy workloads"))
        registry.register(SkillDefinition(name="review", description="Code review"))
        results = registry.search("deploy")
        assert len(results) == 1
        assert results[0].name == "deploy"

    def test_search_by_tag(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(SkillDefinition(name="skill-a", tags=["kubernetes"]))
        results = registry.search("kubernetes")
        assert len(results) == 1

    def test_discover_from_directory(self, tmp_path: Path) -> None:
        from agent33.skills.registry import SkillRegistry

        # Create a YAML skill file
        (tmp_path / "review.yaml").write_text(
            "name: review\ndescription: Code review skill\n",
            encoding="utf-8",
        )
        # Create a directory-based skill
        skill_dir = tmp_path / "deploy"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: deploy\ndescription: Deploy skill\n---\nInstructions.\n",
            encoding="utf-8",
        )

        registry = SkillRegistry()
        count = registry.discover(tmp_path)
        assert count == 2
        assert registry.get("review") is not None
        assert registry.get("deploy") is not None

    def test_discover_recurses_into_hierarchical_categories(self, tmp_path: Path) -> None:
        from agent33.skills.registry import SkillRegistry

        nested_dir = tmp_path / "skills" / "workflow" / "planning" / "planning-with-files"
        nested_dir.mkdir(parents=True)
        (nested_dir / "SKILL.md").write_text(
            "---\nname: planning-with-files\ndescription: Planning skill\n---\nInstructions.\n",
            encoding="utf-8",
        )

        registry = SkillRegistry()
        count = registry.discover(tmp_path)

        assert count == 1
        skill = registry.get("planning-with-files")
        assert skill is not None
        assert skill.category == "workflow/planning"

    def test_discover_nonexistent_dir(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        count = registry.discover(Path("/nonexistent/path"))
        assert count == 0

    def test_discover_skips_bad_files(self, tmp_path: Path) -> None:
        from agent33.skills.registry import SkillRegistry

        # Create a valid and invalid skill
        (tmp_path / "good.yaml").write_text(
            "name: good\ndescription: Good\n",
            encoding="utf-8",
        )
        (tmp_path / "bad.yaml").write_text(
            "not valid yaml: [[[",
            encoding="utf-8",
        )
        registry = SkillRegistry()
        count = registry.discover(tmp_path)
        assert count == 1
        assert registry.get("good") is not None


# ═══════════════════════════════════════════════════════════════════════
# Progressive Disclosure Tests
# ═══════════════════════════════════════════════════════════════════════


class TestProgressiveDisclosure:
    """Test L0/L1/L2 progressive disclosure."""

    def test_l0_metadata(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(SkillDefinition(name="test", description="A test skill"))
        meta = registry.get_metadata_only("test")
        assert meta is not None
        assert meta["name"] == "test"
        assert meta["description"] == "A test skill"

    def test_l0_missing_skill(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        assert registry.get_metadata_only("nonexistent") is None

    def test_l1_instructions(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(
            SkillDefinition(
                name="test",
                instructions="# Test\nDo the thing.",
            )
        )
        instructions = registry.get_full_instructions("test")
        assert instructions is not None
        assert "# Test" in instructions

    def test_l1_missing_skill(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        assert registry.get_full_instructions("nonexistent") is None

    def test_l2_resource(self, tmp_path: Path) -> None:
        from agent33.skills.registry import SkillRegistry

        # Create a skill with a resource file
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "check.py").write_text("print('hello')", encoding="utf-8")

        registry = SkillRegistry()
        registry.register(
            SkillDefinition(
                name="test",
                base_path=tmp_path,
                scripts_dir="scripts",
            )
        )
        content = registry.get_resource("test", "scripts/check.py")
        assert content == "print('hello')"

    def test_l2_path_traversal_blocked(self, tmp_path: Path) -> None:
        from agent33.skills.registry import SkillRegistry

        # Create a file outside the skill directory
        (tmp_path.parent / "secret.txt").write_text("secret", encoding="utf-8")

        registry = SkillRegistry()
        registry.register(SkillDefinition(name="test", base_path=tmp_path))
        content = registry.get_resource("test", "../secret.txt")
        assert content is None

    def test_l2_missing_resource(self, tmp_path: Path) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.register(SkillDefinition(name="test", base_path=tmp_path))
        assert registry.get_resource("test", "nonexistent.txt") is None

    def test_l2_missing_skill(self) -> None:
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        assert registry.get_resource("nonexistent", "file.txt") is None


# ═══════════════════════════════════════════════════════════════════════
# Skill Injector Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSkillInjector:
    """Test skill-to-prompt injection."""

    def _make_injector(self, skills: list[SkillDefinition] | None = None) -> Any:
        from agent33.skills.injection import SkillInjector
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        for skill in skills or []:
            registry.register(skill)
        return SkillInjector(registry)

    def test_metadata_block(self) -> None:
        injector = self._make_injector(
            [
                SkillDefinition(name="deploy", description="Deploy workloads"),
                SkillDefinition(name="review", description="Code review"),
            ]
        )
        block = injector.build_skill_metadata_block(["deploy", "review"])
        assert "# Available Skills" in block
        assert "deploy: Deploy workloads" in block
        assert "review: Code review" in block

    def test_metadata_block_empty_skills(self) -> None:
        injector = self._make_injector()
        block = injector.build_skill_metadata_block([])
        assert "(none)" in block

    def test_metadata_block_missing_skill(self) -> None:
        injector = self._make_injector()
        block = injector.build_skill_metadata_block(["nonexistent"])
        assert "(none)" in block

    def test_instructions_block(self) -> None:
        injector = self._make_injector(
            [
                SkillDefinition(
                    name="deploy",
                    instructions="# Deploy Guide\nStep 1: ...",
                    allowed_tools=["shell", "file_ops"],
                    approval_required_for=["kubectl apply"],
                    autonomy_level="supervised",
                ),
            ]
        )
        block = injector.build_skill_instructions_block("deploy")
        assert "# Active Skill: deploy" in block
        assert "## Governance" in block
        assert "shell" in block
        assert "kubectl apply" in block
        assert "supervised" in block
        assert "# Deploy Guide" in block

    def test_instructions_block_missing_skill(self) -> None:
        from agent33.skills.injection import SkillContractError

        injector = self._make_injector()
        with pytest.raises(SkillContractError, match="Active skill not found"):
            injector.build_skill_instructions_block("nonexistent")

    def test_instructions_block_no_governance(self) -> None:
        injector = self._make_injector(
            [
                SkillDefinition(
                    name="simple",
                    instructions="Just do it.",
                ),
            ]
        )
        block = injector.build_skill_instructions_block("simple")
        assert "## Governance" not in block
        assert "Just do it." in block

    def test_validate_active_skills_rejects_user_only_auto_activation(self) -> None:
        from agent33.skills.injection import SkillContractError

        injector = self._make_injector(
            [
                SkillDefinition(
                    name="deploy",
                    invocation_mode=SkillInvocationMode.USER_ONLY,
                )
            ]
        )

        with pytest.raises(SkillContractError, match="requires user invocation"):
            injector.validate_active_skills(["deploy"], invocation_source="model")

        assert injector.validate_active_skills(["deploy"], invocation_source="user")[0].name == (
            "deploy"
        )

    def test_validate_active_skills_rejects_conflicting_tool_contract(self) -> None:
        from agent33.skills.injection import SkillContractError

        injector = self._make_injector(
            [
                SkillDefinition(
                    name="unsafe",
                    allowed_tools=["shell"],
                    disallowed_tools=["shell"],
                )
            ]
        )

        with pytest.raises(SkillContractError, match="both allows and blocks"):
            injector.validate_active_skills(["unsafe"])


# ═══════════════════════════════════════════════════════════════════════
# Tool Context Resolution Tests
# ═══════════════════════════════════════════════════════════════════════


class TestToolContextResolution:
    """Test skill-driven tool context merging."""

    def _make_injector(self, skills: list[SkillDefinition] | None = None) -> Any:
        from agent33.skills.injection import SkillInjector
        from agent33.skills.registry import SkillRegistry

        registry = SkillRegistry()
        for skill in skills or []:
            registry.register(skill)
        return SkillInjector(registry)

    def _make_context(
        self,
        command_allowlist: list[str] | None = None,
        path_allowlist: list[str] | None = None,
    ) -> Any:
        from agent33.tools.base import ToolContext

        return ToolContext(
            user_scopes=["tools:read"],
            command_allowlist=command_allowlist or [],
            path_allowlist=path_allowlist or [],
            domain_allowlist=["example.com"],
            requested_by="tester",
            tenant_id="tenant-a",
            session_id="session-a",
            tool_policies={"shell": "ask"},
        )

    def test_no_skills_preserves_context(self) -> None:
        injector = self._make_injector()
        base = self._make_context(command_allowlist=["ls", "cat"])
        result = injector.resolve_tool_context([], base)
        # No skills active: base context passes through
        assert sorted(result.command_allowlist) == ["cat", "ls"]
        assert result.user_scopes == ["tools:read"]
        assert result.domain_allowlist == ["example.com"]
        assert result.requested_by == "tester"
        assert result.tenant_id == "tenant-a"
        assert result.session_id == "session-a"
        assert result.tool_policies == {"shell": "ask"}

    def test_skill_narrows_allowlist(self) -> None:
        injector = self._make_injector(
            [
                SkillDefinition(
                    name="restricted",
                    allowed_tools=["shell", "file_ops"],
                ),
            ]
        )
        base = self._make_context(command_allowlist=["shell", "file_ops", "browser"])
        result = injector.resolve_tool_context(["restricted"], base)
        assert set(result.command_allowlist) == {"file_ops", "shell"}

    def test_skill_blocks_tools(self) -> None:
        injector = self._make_injector(
            [
                SkillDefinition(
                    name="safe",
                    allowed_tools=["shell", "file_ops"],
                    disallowed_tools=["shell"],
                ),
            ]
        )
        base = self._make_context(command_allowlist=["shell", "file_ops", "browser"])
        result = injector.resolve_tool_context(["safe"], base)
        assert "shell" not in result.command_allowlist
        assert "file_ops" in result.command_allowlist

    def test_multiple_skills_intersect(self) -> None:
        injector = self._make_injector(
            [
                SkillDefinition(name="a", allowed_tools=["shell", "file_ops", "browser"]),
                SkillDefinition(name="b", allowed_tools=["file_ops", "web_fetch"]),
            ]
        )
        base = self._make_context(command_allowlist=["shell", "file_ops", "browser", "web_fetch"])
        result = injector.resolve_tool_context(["a", "b"], base)
        # Intersection of a ∩ b ∩ base = {file_ops}
        assert result.command_allowlist == ["file_ops"]


# ═══════════════════════════════════════════════════════════════════════
# Agent Definition Integration Tests
# ═══════════════════════════════════════════════════════════════════════


class TestAgentDefinitionSkills:
    """Test that AgentDefinition accepts skills field."""

    def test_default_empty_skills(self) -> None:
        from agent33.agents.definition import AgentDefinition

        defn = AgentDefinition(name="test-agent", version="1.0.0", role="implementer")
        assert defn.skills == []

    def test_skills_field_accepted(self) -> None:
        from agent33.agents.definition import AgentDefinition

        defn = AgentDefinition(
            name="test-agent",
            version="1.0.0",
            role="implementer",
            skills=["deploy", "review"],
        )
        assert defn.skills == ["deploy", "review"]

    def test_existing_json_still_loads(self) -> None:
        """Legacy agent JSON without skills field still loads."""
        from agent33.agents.definition import AgentDefinition

        data = {
            "name": "legacy-agent",
            "version": "1.0.0",
            "role": "implementer",
            "description": "A legacy agent",
        }
        defn = AgentDefinition.model_validate(data)
        assert defn.skills == []


# ═══════════════════════════════════════════════════════════════════════
# Config Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSkillConfig:
    """Test skill-related config settings."""

    def test_skill_config_defaults(self) -> None:
        from agent33.config import Settings

        s = Settings()
        assert s.skill_definitions_dir == "skills"
        assert s.skill_max_instructions_chars == 16000
