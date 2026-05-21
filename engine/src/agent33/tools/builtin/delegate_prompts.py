"""Prompt construction and tool filtering helpers for subagent delegation."""

from __future__ import annotations

BLOCKED_TOOLS: frozenset[str] = frozenset(
    {
        "delegate_subtask",  # no recursive delegation
        "clarify",  # children must not interrupt the user
    }
)


def build_child_system_prompt(goal: str, context: str) -> str:
    """Build a focused system prompt for a delegated child agent.

    The prompt gives the child a clear mission statement, any background
    context supplied by the parent, and safety guardrails. It intentionally
    does *not* include the parent's conversation history so the child
    operates with fresh context.

    Parameters
    ----------
    goal:
        The objective the child agent must accomplish.
    context:
        Optional background information from the parent agent.
    """
    parts: list[str] = [
        "# Delegated Subtask",
        "",
        "You are a focused worker agent executing a specific subtask.",
        "Complete the goal below and report your results concisely.",
        "",
        "## Goal",
        goal,
    ]

    if context.strip():
        parts.extend(
            [
                "",
                "## Background Context",
                context,
            ]
        )

    parts.extend(
        [
            "",
            "## Instructions",
            "- Focus exclusively on the stated goal.",
            "- Use the tools available to you to accomplish the task.",
            "- When finished, provide a concise summary of what you accomplished.",
            "- Do not ask the user for clarification; work with what you have.",
            "- Do not attempt to delegate to other agents.",
            "",
            "## Safety Rules",
            "- Never expose secrets, API keys, or credentials in output.",
            "- Never execute destructive operations without explicit approval.",
            "- Treat all user data as sensitive.",
            "",
            "## Output Format",
            "Respond with valid JSON containing a 'summary' field describing your results.",
        ]
    )

    return "\n".join(parts)


def strip_blocked_tools(tool_names: list[str]) -> list[str]:
    """Remove blocked tools from a list of tool names.

    Parameters
    ----------
    tool_names:
        The full set of tool names the parent wants the child to access.

    Returns
    -------
    list[str]
        Filtered list with all blocked tools removed.
    """
    return [name for name in tool_names if name not in BLOCKED_TOOLS]
