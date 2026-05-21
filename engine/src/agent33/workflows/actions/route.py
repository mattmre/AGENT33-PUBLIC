"""Action that uses an LLM to route a query to the best agent."""

from __future__ import annotations

import json
from typing import Any

import structlog

logger = structlog.get_logger()

# Module-level references set during app startup via the helpers below.
_model_router: Any | None = None
_agent_registry: Any | None = None


def set_router(router: Any) -> None:
    """Wire the model router so route actions can call the LLM."""
    global _model_router  # noqa: PLW0603
    _model_router = router


def set_registry(registry: Any) -> None:
    """Wire the agent registry so route actions can list candidates."""
    global _agent_registry  # noqa: PLW0603
    _agent_registry = registry


async def execute(
    query: str | None = None,
    candidates: list[str] | None = None,
    model: str = "llama3.2",
    inputs: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Use an LLM to select the best agent for a given query.

    Builds a candidate list from the agent registry (optionally
    filtered by *candidates*), prompts the LLM to pick the most
    appropriate agent, and returns the selection with a confidence
    score.

    Args:
        query: The user request to route.
        candidates: Optional list of agent names to restrict
            selection to.
        model: Model identifier to use for routing.
        inputs: Additional context (unused, kept for action
            signature consistency).
        dry_run: If True, return candidate list without calling
            the LLM.

    Returns:
        A dict with ``selected_agent``, ``confidence``, and
        ``reason``.

    Raises:
        ValueError: If *query* is empty or no candidates are
            available.
    """
    if not query:
        raise ValueError("route action requires a 'query' field")

    inputs = inputs or {}

    # Build candidate list from registry or explicit names.
    agent_descriptions: list[dict[str, str]] = []

    if _agent_registry is not None:
        all_agents = _agent_registry.list_all()
        for agent_def in all_agents:
            if candidates and agent_def.name not in candidates:
                continue
            agent_descriptions.append(
                {
                    "name": agent_def.name,
                    "description": agent_def.description or "",
                    "role": agent_def.role.value,
                }
            )
    elif candidates:
        agent_descriptions = [{"name": c, "description": "", "role": "worker"} for c in candidates]

    if not agent_descriptions:
        raise ValueError("No candidate agents available for routing")

    logger.info(
        "route",
        query=query[:100],
        candidates=len(agent_descriptions),
        dry_run=dry_run,
    )

    if dry_run:
        return {
            "dry_run": True,
            "candidates": [a["name"] for a in agent_descriptions],
        }

    if _model_router is None:
        # Fallback: return first candidate when no LLM is available.
        return {
            "selected_agent": agent_descriptions[0]["name"],
            "confidence": 0.0,
            "reason": "no_router",
        }

    from agent33.llm.base import ChatMessage

    system_prompt = (
        "You are an agent router. Given a user query and a list "
        "of available agents, select the single best agent to "
        "handle the request. Respond with JSON: "
        '{"agent": "agent_name", "confidence": 0.0-1.0, '
        '"reason": "brief explanation"}'
    )
    agent_list = "\n".join(
        f"- {a['name']} ({a['role']}): {a['description']}" for a in agent_descriptions
    )
    user_msg = f"Available agents:\n{agent_list}\n\nUser query: {query}"

    response = await _model_router.complete(
        [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_msg),
        ],
        model=model,
        temperature=0.1,
        max_tokens=200,
    )

    # Parse LLM response — tolerate markdown fenced blocks.
    try:
        raw = response.content.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            inner: list[str] = []
            in_block = False
            for line in lines:
                if line.strip().startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.strip() == "```" and in_block:
                    break
                if in_block:
                    inner.append(line)
            raw = "\n".join(inner).strip()
        parsed = json.loads(raw)
        selected = parsed.get("agent", agent_descriptions[0]["name"])
        confidence = float(parsed.get("confidence", 0.5))
        reason = parsed.get("reason", "")
    except (json.JSONDecodeError, KeyError, ValueError):
        selected = agent_descriptions[0]["name"]
        confidence = 0.0
        reason = "parse_error"

    # Validate the LLM's selection is in the candidate list
    valid_names = {a["name"] for a in agent_descriptions}
    if selected not in valid_names:
        logger.warning(
            "route_invalid_selection",
            selected=selected,
            valid=list(valid_names),
        )
        selected = agent_descriptions[0]["name"]
        confidence = 0.0
        reason = f"invalid_selection (LLM chose unknown agent, defaulting to {selected})"

    return {
        "selected_agent": selected,
        "confidence": confidence,
        "reason": reason,
    }
