"""Skill format adapters for external compatibility.

Adapts external skill formats (SkillsBench, MCP tools) into AGENT-33's
SkillDefinition model.  Each adapter implements the SkillFormatAdapter
protocol.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import structlog

from agent33.skills.definition import (
    SkillDefinition,
    SkillExecutionContext,
    SkillInvocationMode,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = structlog.get_logger()


class SkillFormatAdapter(ABC):
    """Base class for adapting external skill formats to SkillDefinition."""

    @abstractmethod
    def can_handle(self, path: Path) -> bool:
        """Check if this adapter can handle the given path."""
        ...

    @abstractmethod
    def load(self, path: Path) -> list[SkillDefinition]:
        """Load and convert skills from the given path."""
        ...


class SkillsBenchAdapter(SkillFormatAdapter):
    """Adapt SkillsBench skill directories to AGENT-33 SkillDefinitions.

    SkillsBench uses the same SKILL.md format with YAML frontmatter
    as AGENT-33. Key differences handled:
    - ``assets/`` directory mapped to ``references``
    - Missing governance fields filled with safe defaults
    - Lighter frontmatter (name, description, version, tags only)
    """

    def can_handle(self, path: Path) -> bool:
        """Check if path is a SkillsBench-style skill directory.

        SkillsBench skills are directories containing a SKILL.md file.
        """
        if path.is_dir():
            return (path / "SKILL.md").is_file()
        return path.name == "SKILL.md"

    def load(self, path: Path) -> list[SkillDefinition]:
        """Load SkillsBench skills from a directory.

        If path is a directory of skill subdirectories, loads all of them.
        If path is a single skill directory (has SKILL.md), loads just that one.
        """
        from agent33.skills.loader import load_from_skillmd

        skills: list[SkillDefinition] = []

        if path.is_file() and path.name == "SKILL.md":
            # Single SKILL.md file
            skill = self._adapt_skill(load_from_skillmd(path), path.parent)
            skills.append(skill)
        elif path.is_dir() and (path / "SKILL.md").is_file():
            # Single skill directory
            skill = self._adapt_skill(load_from_skillmd(path / "SKILL.md"), path)
            skills.append(skill)
        elif path.is_dir():
            # Directory of skill subdirectories
            for entry in sorted(path.iterdir()):
                if entry.is_dir() and (entry / "SKILL.md").is_file():
                    try:
                        skill = self._adapt_skill(load_from_skillmd(entry / "SKILL.md"), entry)
                        skills.append(skill)
                    except Exception:
                        logger.warning(
                            "skillsbench_skill_load_failed",
                            path=str(entry),
                            exc_info=True,
                        )

        return skills

    def _adapt_skill(self, skill: SkillDefinition, skill_dir: Path) -> SkillDefinition:
        """Apply SkillsBench-specific adaptations.

        - Map assets/ to references
        - Fill governance defaults
        """
        updates: dict[str, Any] = {}

        # Map assets/ directory to references
        assets_dir = skill_dir / "assets"
        if assets_dir.is_dir():
            asset_files = [
                str(f.relative_to(skill_dir)) for f in sorted(assets_dir.rglob("*")) if f.is_file()
            ]
            existing_refs = list(skill.references)
            existing_refs.extend(asset_files)
            updates["references"] = existing_refs

        # Ensure safe governance defaults
        if not skill.invocation_mode:
            updates["invocation_mode"] = SkillInvocationMode.BOTH
        if not skill.execution_context:
            updates["execution_context"] = SkillExecutionContext.INLINE

        if updates:
            skill = skill.model_copy(update=updates)

        return skill


class MCPToolAdapter(SkillFormatAdapter):
    """Adapt MCP tool definitions to AGENT-33 SkillDefinitions.

    Converts MCP tool JSON Schema definitions into skill definitions
    with the tool's description as instructions and its parameters
    encoded as tool_parameter_defaults.
    """

    def can_handle(self, path: Path) -> bool:
        """Check if path contains MCP tool definitions (JSON files)."""
        if path.is_file() and path.suffix == ".json":
            return True
        if path.is_dir():
            return any(f.suffix == ".json" for f in path.iterdir())
        return False

    def load(self, path: Path) -> list[SkillDefinition]:
        """Load MCP tool definitions from JSON files."""
        import json

        skills: list[SkillDefinition] = []

        files: list[Path] = []
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(f for f in path.iterdir() if f.suffix == ".json"))

        for fpath in files:
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    for tool_def in data:
                        skill = self._convert_tool(tool_def, fpath)
                        if skill:
                            skills.append(skill)
                elif isinstance(data, dict):
                    skill = self._convert_tool(data, fpath)
                    if skill:
                        skills.append(skill)
            except Exception:
                logger.warning("mcp_tool_load_failed", path=str(fpath), exc_info=True)

        return skills

    def _convert_tool(self, tool_def: dict[str, Any], source_path: Path) -> SkillDefinition | None:
        """Convert a single MCP tool definition to a SkillDefinition."""
        name = tool_def.get("name")
        if not name:
            return None

        description = tool_def.get("description", "")
        parameters = tool_def.get("inputSchema", tool_def.get("parameters", {}))

        # Generate instructions from description + parameters
        instructions_parts = [f"# {name}", ""]
        if description:
            instructions_parts.append(description)
            instructions_parts.append("")

        if parameters and isinstance(parameters, dict):
            props = parameters.get("properties", {})
            if props:
                instructions_parts.append("## Parameters")
                for param_name, param_info in props.items():
                    param_desc = param_info.get("description", "")
                    param_type = param_info.get("type", "any")
                    instructions_parts.append(f"- **{param_name}** ({param_type}): {param_desc}")

        return SkillDefinition(
            name=name,
            version="1.0.0",
            description=description,
            instructions="\n".join(instructions_parts),
            invocation_mode=SkillInvocationMode.BOTH,
            execution_context=SkillExecutionContext.INLINE,
            base_path=source_path.parent,
        )
