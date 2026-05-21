"""Slash-command parser and command registry for skill activation (Phase 54).

Provides hermes-agent-style ``/skill-name`` UX:
- ``/research-agent analyse this codebase`` activates the *research-agent*
  skill with "analyse this codebase" as the instruction.
- ``/deploy --env staging --dry-run`` parses structured flags.
- Session preloading injects L1 instructions into the system prompt for
  all preloaded skills, so they persist across an entire conversation.
"""

from __future__ import annotations

import logging
import re
import shlex
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Slash-command scanning
# ------------------------------------------------------------------

_KEBAB_RE = re.compile(r"[_\s]+")


def _to_slash_command(skill_name: str) -> str:
    """Convert a skill name to its canonical slash-command form.

    ``research_agent`` -> ``/research-agent``
    ``kubernetes-deploy`` -> ``/kubernetes-deploy``
    """
    return "/" + _KEBAB_RE.sub("-", skill_name.strip().lower())


def scan_skill_commands(registry: SkillRegistry) -> dict[str, str]:
    """Build a mapping of slash-commands to skill names.

    Iterates over all registered skills and produces one ``/kebab-name``
    entry for each skill.  If a skill defines ``command_name``, that
    takes priority over the auto-derived kebab name.

    The returned dict maps ``{"/kebab-name": "original-skill-name"}``.
    """
    commands: dict[str, str] = {}
    for skill in registry.list_all():
        if skill.command_name:
            cmd = "/" + skill.command_name.strip().lower()
        else:
            cmd = _to_slash_command(skill.name)
        commands[cmd] = skill.name
    return commands


# ------------------------------------------------------------------
# Structured argument parsing
# ------------------------------------------------------------------


class ParsedCommand(BaseModel):
    """Result of parsing a structured slash-command invocation.

    Examples::

        /deploy staging --dry-run --replicas 3
          -> command="/deploy", skill_name="deploy",
             args=["staging"], flags={"dry-run": True, "replicas": "3"},
             raw_input="/deploy staging --dry-run --replicas 3"

        /research "neural networks" --depth 2
          -> args=["neural networks"], flags={"depth": "2"}
    """

    command: str = Field(description="The matched slash-command (e.g. '/deploy').")
    skill_name: str = Field(description="The resolved skill name.")
    args: list[str] = Field(
        default_factory=list,
        description="Positional arguments after the command.",
    )
    flags: dict[str, str | bool] = Field(
        default_factory=dict,
        description="Named flags (--key value or --flag for booleans).",
    )
    raw_input: str = Field(description="The original user input string.")
    raw_args_string: str = Field(
        default="",
        description="The raw argument string after command extraction.",
    )


def parse_args(args_string: str) -> tuple[list[str], dict[str, str | bool]]:
    """Parse a raw argument string into positional args and flags.

    Supports:
    - Positional arguments: ``arg1 arg2``
    - Quoted arguments: ``"hello world"`` or ``'hello world'``
    - Flags with values: ``--key value``
    - Boolean flags: ``--flag`` (no subsequent value)
    - Short flags: ``-v`` (treated as boolean)

    Returns ``(positional_args, flags_dict)``.
    """
    if not args_string.strip():
        return [], {}

    try:
        tokens = shlex.split(args_string, posix=True)
    except ValueError:
        # If shlex fails (unmatched quotes), fall back to simple split
        tokens = args_string.split()

    positional: list[str] = []
    flags: dict[str, str | bool] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("--"):
            key = token[2:]
            if not key:
                i += 1
                continue
            # Check if next token is a value (not another flag)
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                flags[key] = tokens[i + 1]
                i += 2
            else:
                flags[key] = True
                i += 1
        elif token.startswith("-") and len(token) > 1 and not token[1:].isdigit():
            # Short flag: -v, -n etc. (but not negative numbers like -3)
            key = token[1:]
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                flags[key] = tokens[i + 1]
                i += 2
            else:
                flags[key] = True
                i += 1
        else:
            positional.append(token)
            i += 1

    return positional, flags


# ------------------------------------------------------------------
# Slash-command parsing
# ------------------------------------------------------------------


def parse_slash_command(
    text: str,
    commands: dict[str, str],
) -> tuple[str, str] | None:
    """Parse user text for a leading slash-command.

    Returns ``(skill_name, remaining_instruction)`` when a match is found,
    or ``None`` when the text does not start with a registered command.

    When multiple commands share a prefix (e.g. ``/deploy`` and
    ``/deploy-k8s``), the longest matching command wins.
    """
    text = text.strip()
    if not text.startswith("/"):
        return None

    # Sort by length descending so the longest (most specific) command
    # is tried first.
    for cmd in sorted(commands.keys(), key=len, reverse=True):
        if text == cmd or text.startswith(cmd + " "):
            instruction = text[len(cmd) :].strip()
            return (commands[cmd], instruction)

    return None


def parse_slash_command_structured(
    text: str,
    commands: dict[str, str],
) -> ParsedCommand | None:
    """Parse user text into a fully structured ``ParsedCommand``.

    Unlike ``parse_slash_command`` which returns a simple tuple, this
    function also parses positional args, flags, and quoted strings.

    Returns ``None`` when the text does not match a registered command.
    """
    basic = parse_slash_command(text, commands)
    if basic is None:
        return None

    skill_name, raw_args_string = basic

    # Find the matched command key
    matched_cmd = ""
    for cmd, sname in commands.items():
        if sname == skill_name:
            matched_cmd = cmd
            break

    args, flags = parse_args(raw_args_string)

    return ParsedCommand(
        command=matched_cmd,
        skill_name=skill_name,
        args=args,
        flags=flags,
        raw_input=text.strip(),
        raw_args_string=raw_args_string,
    )


# ------------------------------------------------------------------
# Command Registry
# ------------------------------------------------------------------


class CommandInfo(BaseModel):
    """Metadata for a single slash-command, used in discovery listings."""

    command: str = Field(description="The slash-command (e.g. '/deploy').")
    skill_name: str = Field(description="The backing skill name.")
    description: str = Field(default="", description="Skill description.")
    help_text: str = Field(default="", description="Command-specific help text.")
    category: str = Field(default="", description="Skill category.")
    tags: list[str] = Field(default_factory=list, description="Skill tags.")
    status: str = Field(default="active", description="Skill status.")


class CommandRegistry:
    """Maps slash-commands to skills and provides discovery metadata.

    Wraps a ``SkillRegistry`` and builds the command mapping on demand.
    The mapping is rebuilt each time ``refresh()`` is called or on first
    access to ``commands``.
    """

    def __init__(self, skill_registry: SkillRegistry) -> None:
        self._skill_registry = skill_registry
        self._commands: dict[str, str] | None = None

    @property
    def commands(self) -> dict[str, str]:
        """Return the current command-to-skill mapping, building it if needed."""
        if self._commands is None:
            self.refresh()
        assert self._commands is not None
        return self._commands

    def refresh(self) -> None:
        """Rebuild the command mapping from the current skill registry state."""
        self._commands = scan_skill_commands(self._skill_registry)
        logger.debug("command_registry_refreshed", extra={"count": len(self._commands)})

    def resolve(self, text: str) -> ParsedCommand | None:
        """Parse user text and resolve to a structured command invocation."""
        return parse_slash_command_structured(text, self.commands)

    def list_commands(self) -> list[CommandInfo]:
        """Return metadata for all registered commands, sorted by command name."""
        result: list[CommandInfo] = []
        for cmd, skill_name in sorted(self.commands.items()):
            skill = self._skill_registry.get(skill_name)
            if skill is None:
                continue
            result.append(
                CommandInfo(
                    command=cmd,
                    skill_name=skill_name,
                    description=skill.description,
                    help_text=skill.command_help or skill.description,
                    category=skill.category,
                    tags=list(skill.tags),
                    status=skill.status.value,
                )
            )
        return result

    def get_command_info(self, command: str) -> CommandInfo | None:
        """Get metadata for a single command."""
        skill_name = self.commands.get(command)
        if skill_name is None:
            return None
        skill = self._skill_registry.get(skill_name)
        if skill is None:
            return None
        return CommandInfo(
            command=command,
            skill_name=skill_name,
            description=skill.description,
            help_text=skill.command_help or skill.description,
            category=skill.category,
            tags=list(skill.tags),
            status=skill.status.value,
        )

    @property
    def count(self) -> int:
        """Number of registered commands."""
        return len(self.commands)


# ------------------------------------------------------------------
# Command invocation result
# ------------------------------------------------------------------


class CommandResult(BaseModel):
    """Result of invoking a slash-command."""

    command: str = Field(description="The slash-command that was invoked.")
    skill_name: str = Field(description="The skill that handled the command.")
    success: bool = Field(default=True)
    output: str = Field(default="", description="Command output text.")
    error: str | None = Field(default=None, description="Error message if failed.")
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional result metadata.",
    )


# ------------------------------------------------------------------
# Session preloading
# ------------------------------------------------------------------


def build_preloaded_prompt(
    skill_names: list[str],
    registry: SkillRegistry,
) -> str:
    """Build a system-prompt prefix for session-preloaded skills.

    For each requested skill name:
    - Loads L1 full instructions from the registry.
    - Wraps them in a ``[PRELOADED SKILL: ...]`` header block.

    Skills that cannot be found are silently skipped (they may have been
    removed between session creation and prompt construction).
    """
    blocks: list[str] = []
    for name in skill_names:
        skill = registry.get(name)
        if skill is None:
            continue
        header = f"[PRELOADED SKILL: {skill.name}]"
        body = skill.instructions if skill.instructions else skill.description
        blocks.append(f"{header}\n{body}")
    return "\n\n".join(blocks)
