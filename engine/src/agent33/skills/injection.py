"""Skill-to-prompt injection and tool context resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent33.skills.definition import SkillDefinition
    from agent33.skills.registry import SkillRegistry
    from agent33.tools.base import ToolContext


class SkillContractError(ValueError):
    """Raised when a skill cannot be loaded or invoked under its contract."""


class SkillInjector:
    """Injects skill content into agent system prompts.

    Supports progressive disclosure:
    - L0: compact metadata block (name + description) for all available skills
    - L1: full instructions block for actively invoked skills
    - L2: on-demand resource loading via registry.get_resource()
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Prompt Building
    # ------------------------------------------------------------------

    def build_skill_metadata_block(self, skill_names: list[str]) -> str:
        """L0: Build a compact skill list for the base system prompt.

        Returns a section listing available skills so the LLM knows what
        capabilities can be activated.
        """
        lines = ["# Available Skills"]
        for name in sorted(skill_names):
            meta = self._registry.get_metadata_only(name)
            if meta:
                lines.append(f"- {meta['name']}: {meta['description']}")
        if len(lines) == 1:
            lines.append("(none)")
        return "\n".join(lines)

    def build_skill_instructions_block(self, skill_name: str) -> str:
        """L1: Build full instructions block for an active skill.

        Includes governance metadata (allowed tools, approval requirements)
        and the complete skill instructions.
        """
        skill = self._registry.get(skill_name)
        if skill is None:
            raise SkillContractError(f"Active skill not found: {skill_name}")

        lines = [f"# Active Skill: {skill.name}"]

        # Governance info
        governance_lines: list[str] = []
        if skill.allowed_tools:
            governance_lines.append(f"- Allowed tools: {', '.join(skill.allowed_tools)}")
        if skill.disallowed_tools:
            governance_lines.append(f"- Blocked tools: {', '.join(skill.disallowed_tools)}")
        if skill.autonomy_level:
            governance_lines.append(f"- Autonomy: {skill.autonomy_level}")
        if skill.approval_required_for:
            governance_lines.append(
                f"- Requires approval for: {', '.join(skill.approval_required_for)}"
            )
        if governance_lines:
            lines.append("## Governance")
            lines.extend(governance_lines)

        # Instructions
        if skill.instructions:
            lines.append("")
            lines.append(skill.instructions)

        return "\n".join(lines)

    def build_preloaded_instructions(self, skill_names: list[str]) -> str:
        """Build a combined instructions block for session-preloaded skills.

        Unlike ``build_skill_instructions_block`` (which builds a block for
        a *single* active skill), this method builds a system-prompt section
        for *all* preloaded skills at once.  Each skill's L1 instructions
        are wrapped in a ``[SYSTEM: ...]`` header so the LLM knows the
        skill is always available during the session.
        """
        from agent33.skills.slash_commands import build_preloaded_prompt

        return build_preloaded_prompt(skill_names, self._registry)

    def validate_active_skills(
        self,
        active_skills: list[str],
        *,
        invocation_source: str = "model",
    ) -> list[SkillDefinition]:
        """Return active skill definitions or fail before prompt/tool execution."""
        resolved: list[SkillDefinition] = []
        for name in active_skills:
            skill = self._registry.get(name)
            if skill is None:
                raise SkillContractError(f"Active skill not found: {name}")
            if skill.status.value != "active":
                raise SkillContractError(
                    f"Active skill {name} is not active: {skill.status.value}"
                )
            if skill.invocation_mode.value == "user-only" and invocation_source != "user":
                raise SkillContractError(
                    f"Skill {name} requires user invocation and cannot be auto-activated"
                )
            if skill.invocation_mode.value == "llm-only" and invocation_source == "user":
                raise SkillContractError(
                    f"Skill {name} is model-invoked only and cannot be user-preloaded"
                )
            overlap = set(skill.allowed_tools) & set(skill.disallowed_tools)
            if overlap:
                names = ", ".join(sorted(overlap))
                raise SkillContractError(f"Skill {name} both allows and blocks tools: {names}")
            resolved.append(skill)
        return resolved

    # ------------------------------------------------------------------
    # Tool Context Resolution
    # ------------------------------------------------------------------

    def resolve_tool_context(
        self,
        active_skills: list[str],
        base_context: ToolContext,
    ) -> ToolContext:
        """Merge tool restrictions from active skills into the ToolContext.

        Skills narrow tool access: the resulting allowlist is the intersection
        of the agent's base allowlist and the skill's allowed_tools.
        Disallowed tools are always removed.
        """
        from agent33.tools.base import ToolContext as _ToolContext

        # Start with the base context's values
        allowed = set(base_context.command_allowlist) if base_context.command_allowlist else None
        blocked: set[str] = set()

        for name in active_skills:
            skill = self._registry.get(name)
            if skill is None:
                continue

            # Accumulate blocked tools
            blocked.update(skill.disallowed_tools)

            # Intersect allowed tools
            if skill.allowed_tools:
                skill_allowed = set(skill.allowed_tools)
                allowed = skill_allowed if allowed is None else allowed & skill_allowed

        # Remove blocked from allowed
        if allowed is not None:
            allowed -= blocked

        # Build a new context with the merged allowlist
        new_allowlist = sorted(allowed) if allowed is not None else []
        return _ToolContext(
            user_scopes=base_context.user_scopes,
            command_allowlist=new_allowlist,
            path_allowlist=base_context.path_allowlist,
            domain_allowlist=base_context.domain_allowlist,
            working_dir=base_context.working_dir,
            tool_policies=base_context.tool_policies,
            requested_by=base_context.requested_by,
            tenant_id=base_context.tenant_id,
            session_id=base_context.session_id,
            event_sink=base_context.event_sink,
        )
