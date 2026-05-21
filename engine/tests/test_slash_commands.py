"""Tests for Phase 54: Skill Slash-Commands & Session Preloading.

Tests cover:
- Slash-command scanning from a SkillRegistry
- Command parsing with valid/invalid inputs
- Longest-match priority when commands share prefixes
- Kebab-case conversion of skill names
- Preloaded-prompt building
- Supporting-file discovery from skill directories
- SkillInjector.build_preloaded_instructions integration
- SkillDefinition.supporting_files field
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent33.skills.definition import SkillDefinition
from agent33.skills.registry import SkillRegistry
from agent33.skills.slash_commands import (
    build_preloaded_prompt,
    parse_slash_command,
    scan_skill_commands,
)

if TYPE_CHECKING:
    from pathlib import Path


# ===================================================================
# Helpers
# ===================================================================


def _make_registry(skills: list[SkillDefinition] | None = None) -> SkillRegistry:
    registry = SkillRegistry()
    for skill in skills or []:
        registry.register(skill)
    return registry


# ===================================================================
# scan_skill_commands
# ===================================================================


class TestScanSkillCommands:
    """Test slash-command scanning from a registry."""

    def test_empty_registry(self) -> None:
        registry = _make_registry()
        commands = scan_skill_commands(registry)
        assert commands == {}

    def test_single_skill(self) -> None:
        registry = _make_registry([SkillDefinition(name="research-agent")])
        commands = scan_skill_commands(registry)
        assert commands == {"/research-agent": "research-agent"}

    def test_multiple_skills(self) -> None:
        registry = _make_registry(
            [
                SkillDefinition(name="deploy"),
                SkillDefinition(name="code-review"),
                SkillDefinition(name="research-agent"),
            ]
        )
        commands = scan_skill_commands(registry)
        assert len(commands) == 3
        assert commands["/deploy"] == "deploy"
        assert commands["/code-review"] == "code-review"
        assert commands["/research-agent"] == "research-agent"

    def test_kebab_case_conversion_underscores(self) -> None:
        registry = _make_registry([SkillDefinition(name="my_cool_skill")])
        commands = scan_skill_commands(registry)
        assert "/my-cool-skill" in commands
        assert commands["/my-cool-skill"] == "my_cool_skill"

    def test_kebab_case_conversion_spaces(self) -> None:
        registry = _make_registry([SkillDefinition(name="my cool skill")])
        commands = scan_skill_commands(registry)
        assert "/my-cool-skill" in commands

    def test_kebab_case_conversion_mixed(self) -> None:
        registry = _make_registry([SkillDefinition(name="my_cool skill")])
        commands = scan_skill_commands(registry)
        assert "/my-cool-skill" in commands

    def test_already_kebab_case(self) -> None:
        registry = _make_registry([SkillDefinition(name="already-kebab")])
        commands = scan_skill_commands(registry)
        assert "/already-kebab" in commands

    def test_uppercase_lowered(self) -> None:
        registry = _make_registry([SkillDefinition(name="MySkill")])
        commands = scan_skill_commands(registry)
        assert "/myskill" in commands
        assert commands["/myskill"] == "MySkill"


# ===================================================================
# parse_slash_command
# ===================================================================


class TestParseSlashCommand:
    """Test slash-command parsing."""

    def test_valid_command_with_instruction(self) -> None:
        commands = {"/deploy": "deploy", "/review": "review"}
        result = parse_slash_command("/deploy roll out v2.0", commands)
        assert result is not None
        assert result[0] == "deploy"
        assert result[1] == "roll out v2.0"

    def test_valid_command_no_instruction(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command("/deploy", commands)
        assert result is not None
        assert result[0] == "deploy"
        assert result[1] == ""

    def test_no_slash_prefix(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command("deploy me something", commands)
        assert result is None

    def test_unknown_command(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command("/unknown do stuff", commands)
        assert result is None

    def test_empty_string(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command("", commands)
        assert result is None

    def test_slash_only(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command("/", commands)
        assert result is None

    def test_leading_whitespace_stripped(self) -> None:
        commands = {"/deploy": "deploy"}
        result = parse_slash_command("  /deploy hello", commands)
        assert result is not None
        assert result[0] == "deploy"
        assert result[1] == "hello"

    def test_longest_match_priority(self) -> None:
        """When /deploy and /deploy-k8s both exist, /deploy-k8s should win."""
        commands = {
            "/deploy": "deploy",
            "/deploy-k8s": "deploy-k8s",
        }
        result = parse_slash_command("/deploy-k8s roll out", commands)
        assert result is not None
        assert result[0] == "deploy-k8s"
        assert result[1] == "roll out"

    def test_short_command_still_works(self) -> None:
        """When text is /deploy but /deploy-k8s also exists, /deploy wins."""
        commands = {
            "/deploy": "deploy",
            "/deploy-k8s": "deploy-k8s",
        }
        result = parse_slash_command("/deploy something", commands)
        assert result is not None
        assert result[0] == "deploy"
        assert result[1] == "something"

    def test_command_without_space_separator(self) -> None:
        """'/deployextra' should NOT match '/deploy' because there's no space separator."""
        commands = {"/deploy": "deploy"}
        result = parse_slash_command("/deployextra", commands)
        assert result is None

    def test_exact_match_no_trailing_text(self) -> None:
        """'/deploy' exactly should match even without trailing space."""
        commands = {"/deploy": "deploy"}
        result = parse_slash_command("/deploy", commands)
        assert result is not None
        assert result[0] == "deploy"
        assert result[1] == ""

    def test_empty_commands_dict(self) -> None:
        result = parse_slash_command("/deploy stuff", {})
        assert result is None


# ===================================================================
# build_preloaded_prompt
# ===================================================================


class TestBuildPreloadedPrompt:
    """Test session-preloaded prompt building."""

    def test_single_skill_with_instructions(self) -> None:
        registry = _make_registry(
            [
                SkillDefinition(
                    name="research-agent",
                    description="Research capabilities",
                    instructions="# Research\nAnalyze codebases and papers.",
                ),
            ]
        )
        prompt = build_preloaded_prompt(["research-agent"], registry)
        assert "[PRELOADED SKILL: research-agent]" in prompt
        assert "# Research" in prompt
        assert "Analyze codebases and papers." in prompt

    def test_multiple_skills(self) -> None:
        registry = _make_registry(
            [
                SkillDefinition(
                    name="deploy",
                    description="Deploy workloads",
                    instructions="Step 1: kubectl apply",
                ),
                SkillDefinition(
                    name="review",
                    description="Code review",
                    instructions="Check for bugs.",
                ),
            ]
        )
        prompt = build_preloaded_prompt(["deploy", "review"], registry)
        assert "[PRELOADED SKILL: deploy]" in prompt
        assert "[PRELOADED SKILL: review]" in prompt
        assert "Step 1: kubectl apply" in prompt
        assert "Check for bugs." in prompt

    def test_missing_skill_skipped(self) -> None:
        registry = _make_registry([SkillDefinition(name="deploy", instructions="Deploy things.")])
        prompt = build_preloaded_prompt(["deploy", "nonexistent"], registry)
        assert "[PRELOADED SKILL: deploy]" in prompt
        assert "nonexistent" not in prompt

    def test_all_skills_missing(self) -> None:
        registry = _make_registry()
        prompt = build_preloaded_prompt(["a", "b"], registry)
        assert prompt == ""

    def test_empty_skill_names(self) -> None:
        registry = _make_registry([SkillDefinition(name="deploy", instructions="Deploy.")])
        prompt = build_preloaded_prompt([], registry)
        assert prompt == ""

    def test_skill_without_instructions_uses_description(self) -> None:
        registry = _make_registry(
            [
                SkillDefinition(
                    name="simple",
                    description="A simple skill",
                    instructions="",
                ),
            ]
        )
        prompt = build_preloaded_prompt(["simple"], registry)
        assert "[PRELOADED SKILL: simple]" in prompt
        assert "A simple skill" in prompt


# ===================================================================
# SkillRegistry.get_supporting_files
# ===================================================================


class TestGetSupportingFiles:
    """Test supporting-file discovery from skill directories."""

    def test_no_supporting_dirs(self, tmp_path: Path) -> None:
        registry = _make_registry([SkillDefinition(name="minimal", base_path=tmp_path)])
        files = registry.get_supporting_files("minimal")
        assert files == []

    def test_references_dir(self, tmp_path: Path) -> None:
        refs = tmp_path / "references"
        refs.mkdir()
        (refs / "readme.txt").write_text("ref content", encoding="utf-8")

        registry = _make_registry([SkillDefinition(name="skill-a", base_path=tmp_path)])
        files = registry.get_supporting_files("skill-a")
        assert "references/readme.txt" in files

    def test_templates_dir(self, tmp_path: Path) -> None:
        tpl = tmp_path / "templates"
        tpl.mkdir()
        (tpl / "deploy.yaml").write_text("template", encoding="utf-8")

        registry = _make_registry([SkillDefinition(name="skill-b", base_path=tmp_path)])
        files = registry.get_supporting_files("skill-b")
        assert "templates/deploy.yaml" in files

    def test_scripts_dir(self, tmp_path: Path) -> None:
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "check.sh").write_text("#!/bin/bash", encoding="utf-8")

        registry = _make_registry([SkillDefinition(name="skill-c", base_path=tmp_path)])
        files = registry.get_supporting_files("skill-c")
        assert "scripts/check.sh" in files

    def test_assets_dir(self, tmp_path: Path) -> None:
        assets = tmp_path / "assets"
        assets.mkdir()
        (assets / "logo.png").write_bytes(b"\x89PNG")

        registry = _make_registry([SkillDefinition(name="skill-d", base_path=tmp_path)])
        files = registry.get_supporting_files("skill-d")
        assert "assets/logo.png" in files

    def test_multiple_dirs_and_nested(self, tmp_path: Path) -> None:
        refs = tmp_path / "references"
        refs.mkdir()
        (refs / "a.md").write_text("a", encoding="utf-8")

        scripts = tmp_path / "scripts"
        scripts.mkdir()
        nested = scripts / "sub"
        nested.mkdir()
        (nested / "deep.py").write_text("deep", encoding="utf-8")

        registry = _make_registry([SkillDefinition(name="skill-e", base_path=tmp_path)])
        files = registry.get_supporting_files("skill-e")
        assert "references/a.md" in files
        assert "scripts/sub/deep.py" in files

    def test_missing_skill(self) -> None:
        registry = _make_registry()
        files = registry.get_supporting_files("nonexistent")
        assert files == []

    def test_skill_without_base_path(self) -> None:
        registry = _make_registry([SkillDefinition(name="no-path")])
        files = registry.get_supporting_files("no-path")
        assert files == []

    def test_non_conventional_dirs_ignored(self, tmp_path: Path) -> None:
        """Directories other than references/templates/scripts/assets are ignored."""
        custom = tmp_path / "custom"
        custom.mkdir()
        (custom / "file.txt").write_text("ignored", encoding="utf-8")

        registry = _make_registry([SkillDefinition(name="skill-f", base_path=tmp_path)])
        files = registry.get_supporting_files("skill-f")
        assert files == []


# ===================================================================
# SkillDefinition.supporting_files field
# ===================================================================


class TestSkillDefinitionSupportingFiles:
    """Test the supporting_files field on SkillDefinition."""

    def test_default_empty(self) -> None:
        skill = SkillDefinition(name="test")
        assert skill.supporting_files == []

    def test_explicit_values(self) -> None:
        skill = SkillDefinition(
            name="test",
            supporting_files=["references/readme.md", "scripts/run.sh"],
        )
        assert skill.supporting_files == ["references/readme.md", "scripts/run.sh"]

    def test_serialization_includes_supporting_files(self) -> None:
        skill = SkillDefinition(
            name="test",
            supporting_files=["templates/deploy.yaml"],
        )
        data = skill.model_dump(mode="json")
        assert data["supporting_files"] == ["templates/deploy.yaml"]


# ===================================================================
# SkillInjector.build_preloaded_instructions
# ===================================================================


class TestSkillInjectorPreloading:
    """Test SkillInjector integration with session preloading."""

    def test_preloaded_instructions(self) -> None:
        from agent33.skills.injection import SkillInjector

        registry = _make_registry(
            [
                SkillDefinition(
                    name="deploy",
                    description="Deploy workloads",
                    instructions="Apply manifests.",
                ),
                SkillDefinition(
                    name="review",
                    description="Code review",
                    instructions="Look for bugs.",
                ),
            ]
        )
        injector = SkillInjector(registry)
        result = injector.build_preloaded_instructions(["deploy", "review"])
        assert "[PRELOADED SKILL: deploy]" in result
        assert "[PRELOADED SKILL: review]" in result
        assert "Apply manifests." in result
        assert "Look for bugs." in result

    def test_preloaded_instructions_empty(self) -> None:
        from agent33.skills.injection import SkillInjector

        registry = _make_registry()
        injector = SkillInjector(registry)
        result = injector.build_preloaded_instructions([])
        assert result == ""

    def test_preloaded_instructions_missing_skill(self) -> None:
        from agent33.skills.injection import SkillInjector

        registry = _make_registry([SkillDefinition(name="deploy", instructions="Deploy.")])
        injector = SkillInjector(registry)
        result = injector.build_preloaded_instructions(["deploy", "nonexistent"])
        assert "[PRELOADED SKILL: deploy]" in result
        assert "nonexistent" not in result
