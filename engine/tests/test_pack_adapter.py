"""Tests for skill format adapters: SkillsBenchAdapter and MCPToolAdapter.

Tests cover: SkillsBench SKILL.md loading, assets/ mapping to references,
MCP tool JSON conversion, adapter can_handle detection, and error handling.
"""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

from agent33.packs.adapter import MCPToolAdapter, SkillsBenchAdapter

if TYPE_CHECKING:
    from pathlib import Path


class TestSkillsBenchAdapter:
    """Test the SkillsBench format adapter."""

    def test_can_handle_skill_directory(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: test\n---\n# Test\n")

        adapter = SkillsBenchAdapter()
        assert adapter.can_handle(skill_dir) is True

    def test_can_handle_no_skill_md(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        adapter = SkillsBenchAdapter()
        assert adapter.can_handle(empty_dir) is False

    def test_can_handle_skill_md_file(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nname: test\n---\n# Test\n")

        adapter = SkillsBenchAdapter()
        assert adapter.can_handle(skill_md) is True

    def test_load_single_skill(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            textwrap.dedent("""\
            ---
            name: my-skill
            version: 1.0.0
            description: A test skill
            tags:
              - test
            ---
            # My Skill
            Do something useful.
            """),
            encoding="utf-8",
        )

        adapter = SkillsBenchAdapter()
        skills = adapter.load(skill_dir)
        assert len(skills) == 1
        assert skills[0].name == "my-skill"
        assert skills[0].description == "A test skill"
        assert "Do something useful" in skills[0].instructions

    def test_load_directory_of_skills(self, tmp_path: Path) -> None:
        """Load from a parent directory containing multiple skill subdirs."""
        for sname in ("skill-a", "skill-b"):
            sdir = tmp_path / sname
            sdir.mkdir()
            (sdir / "SKILL.md").write_text(
                f"---\nname: {sname}\ndescription: {sname}\n---\n# {sname}\n",
                encoding="utf-8",
            )

        adapter = SkillsBenchAdapter()
        skills = adapter.load(tmp_path)
        assert len(skills) == 2
        assert {s.name for s in skills} == {"skill-a", "skill-b"}

    def test_assets_mapped_to_references(self, tmp_path: Path) -> None:
        """SkillsBench assets/ directory should be mapped to references."""
        skill_dir = tmp_path / "asset-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: asset-skill\ndescription: Has assets\n---\n# Asset\n",
            encoding="utf-8",
        )
        assets_dir = skill_dir / "assets"
        assets_dir.mkdir()
        (assets_dir / "data.csv").write_text("a,b,c")
        (assets_dir / "config.json").write_text("{}")

        adapter = SkillsBenchAdapter()
        skills = adapter.load(skill_dir)
        assert len(skills) == 1
        # assets files should appear in references
        refs = skills[0].references
        assert any("data.csv" in r for r in refs)
        assert any("config.json" in r for r in refs)

    def test_load_from_skill_md_file(self, tmp_path: Path) -> None:
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text(
            "---\nname: direct\ndescription: Direct load\n---\n# Direct\n",
            encoding="utf-8",
        )

        adapter = SkillsBenchAdapter()
        skills = adapter.load(skill_md)
        assert len(skills) == 1
        assert skills[0].name == "direct"


class TestMCPToolAdapter:
    """Test the MCP tool format adapter."""

    def test_can_handle_json_file(self, tmp_path: Path) -> None:
        json_file = tmp_path / "tools.json"
        json_file.write_text("{}")

        adapter = MCPToolAdapter()
        assert adapter.can_handle(json_file) is True

    def test_can_handle_non_json(self, tmp_path: Path) -> None:
        txt_file = tmp_path / "tools.txt"
        txt_file.write_text("not json")

        adapter = MCPToolAdapter()
        assert adapter.can_handle(txt_file) is False

    def test_can_handle_dir_with_json(self, tmp_path: Path) -> None:
        (tmp_path / "tool.json").write_text("{}")

        adapter = MCPToolAdapter()
        assert adapter.can_handle(tmp_path) is True

    def test_load_single_tool(self, tmp_path: Path) -> None:
        tool_def = {
            "name": "calculator",
            "description": "Perform arithmetic operations",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "Math expression to evaluate",
                    }
                },
            },
        }
        json_file = tmp_path / "calc.json"
        json_file.write_text(json.dumps(tool_def), encoding="utf-8")

        adapter = MCPToolAdapter()
        skills = adapter.load(json_file)
        assert len(skills) == 1
        assert skills[0].name == "calculator"
        assert "arithmetic" in skills[0].description
        assert "expression" in skills[0].instructions

    def test_load_tool_list(self, tmp_path: Path) -> None:
        tools = [
            {"name": "tool-a", "description": "Tool A"},
            {"name": "tool-b", "description": "Tool B"},
        ]
        json_file = tmp_path / "tools.json"
        json_file.write_text(json.dumps(tools), encoding="utf-8")

        adapter = MCPToolAdapter()
        skills = adapter.load(json_file)
        assert len(skills) == 2
        assert {s.name for s in skills} == {"tool-a", "tool-b"}

    def test_load_tool_without_name_skipped(self, tmp_path: Path) -> None:
        """Tools without a name should be skipped."""
        tool_def = {"description": "No name tool"}
        json_file = tmp_path / "nameless.json"
        json_file.write_text(json.dumps(tool_def), encoding="utf-8")

        adapter = MCPToolAdapter()
        skills = adapter.load(json_file)
        assert len(skills) == 0

    def test_load_tool_with_parameters_section(self, tmp_path: Path) -> None:
        """Supports both inputSchema and parameters keys."""
        tool_def = {
            "name": "fetcher",
            "description": "Fetch data",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
            },
        }
        json_file = tmp_path / "fetch.json"
        json_file.write_text(json.dumps(tool_def), encoding="utf-8")

        adapter = MCPToolAdapter()
        skills = adapter.load(json_file)
        assert len(skills) == 1
        assert "url" in skills[0].instructions

    def test_load_invalid_json_skipped(self, tmp_path: Path) -> None:
        json_file = tmp_path / "bad.json"
        json_file.write_text("not valid json {[}", encoding="utf-8")

        adapter = MCPToolAdapter()
        skills = adapter.load(json_file)
        assert len(skills) == 0
