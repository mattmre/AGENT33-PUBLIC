"""GroupChat workflow action — multi-agent conversation rooms."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.agents.definition import AgentDefinition

logger = logging.getLogger(__name__)


class GroupChatConfig(BaseModel):
    """Configuration for a group chat workflow step."""

    agents: list[str] = Field(..., description="Agent names participating in the chat")
    topic: str = Field(..., description="Initial topic/question for the group")
    max_rounds: int = Field(default=10, ge=1, le=100, description="Maximum conversation rounds")
    speaker_selection: str = Field(
        default="round_robin",
        description="Strategy: round_robin, random, auto, mention",
    )
    termination_phrase: str = Field(
        default="TERMINATE",
        description="Phrase that ends the conversation",
    )
    message_history_limit: int = Field(
        default=20, ge=1, description="Sliding window for message history"
    )


class GroupChatMessage(BaseModel):
    """A single message in the group chat transcript."""

    speaker: str
    content: str
    round_number: int


class GroupChatResult(BaseModel):
    """Result of a group chat execution."""

    transcript: list[GroupChatMessage] = Field(default_factory=list)
    final_message: str = ""
    rounds_completed: int = 0
    termination_reason: str = "max_rounds"
    participating_agents: list[str] = Field(default_factory=list)


async def execute(
    config: GroupChatConfig,
    context: dict[str, Any],
) -> dict[str, Any]:
    """Execute a group chat conversation.

    Args:
        config: GroupChat configuration.
        context: Workflow execution context with agent_registry, model_router, etc.

    Returns:
        Dict with transcript, final_message, rounds_completed.
    """
    from agent33.workflows.actions.speaker_selection import get_selector

    agent_registry = context.get("agent_registry")
    model_router = context.get("model_router")

    if not agent_registry or not model_router:
        return GroupChatResult(
            termination_reason="missing_dependencies",
        ).model_dump()

    # Validate all agents exist
    agents: list[AgentDefinition] = []
    for name in config.agents:
        defn = agent_registry.get(name)
        if defn is None:
            logger.warning("Agent '%s' not found, skipping", name)
            continue
        agents.append(defn)

    if len(agents) < 2:
        return GroupChatResult(
            termination_reason="insufficient_agents",
            participating_agents=[a.name for a in agents],
        ).model_dump()

    selector = get_selector(config.speaker_selection, [a.name for a in agents])
    transcript: list[GroupChatMessage] = []
    chat_history: list[dict[str, str]] = []

    # Start with topic as first user message
    chat_history.append({"role": "user", "content": config.topic})

    for round_num in range(1, config.max_rounds + 1):
        # Select next speaker
        speaker_name = selector.select(chat_history)
        speaker_defn = next((a for a in agents if a.name == speaker_name), None)
        if speaker_defn is None:
            continue

        # Build agent-local messages
        local_messages = _build_local_messages(
            speaker_name, chat_history, config.message_history_limit
        )

        # Call agent via router
        from agent33.llm.base import ChatMessage

        system_prompt = speaker_defn.prompts.system or speaker_defn.description
        messages = [
            ChatMessage(role="system", content=system_prompt),
        ] + [ChatMessage(role=m["role"], content=m["content"]) for m in local_messages]

        model = context.get("model", "default")

        try:
            response = await model_router.complete(
                messages,
                model=model,
                temperature=0.7,
            )
            content = response.content or ""
        except Exception as exc:
            logger.error("Agent '%s' failed: %s", speaker_name, exc)
            content = f"[Error: {exc}]"

        # Record message
        msg = GroupChatMessage(
            speaker=speaker_name,
            content=content,
            round_number=round_num,
        )
        transcript.append(msg)
        chat_history.append(
            {
                "role": "assistant",
                "content": f"[{speaker_name}]: {content}",
            }
        )

        # Check termination
        if config.termination_phrase in content:
            return GroupChatResult(
                transcript=transcript,
                final_message=content,
                rounds_completed=round_num,
                termination_reason="termination_phrase",
                participating_agents=[a.name for a in agents],
            ).model_dump()

    return GroupChatResult(
        transcript=transcript,
        final_message=transcript[-1].content if transcript else "",
        rounds_completed=config.max_rounds,
        termination_reason="max_rounds",
        participating_agents=[a.name for a in agents],
    ).model_dump()


def _build_local_messages(
    speaker: str,
    history: list[dict[str, str]],
    limit: int,
) -> list[dict[str, str]]:
    """Remap chat history for a specific agent's perspective."""
    windowed = history[-limit:]
    local: list[dict[str, str]] = []
    for msg in windowed:
        content = msg["content"]
        if content.startswith(f"[{speaker}]:"):
            # Own message → assistant
            local.append({"role": "assistant", "content": content.split("]: ", 1)[1]})
        else:
            # Others → user
            local.append({"role": "user", "content": content})
    return local
