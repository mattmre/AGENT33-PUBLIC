"""RAG-integrated assistant archetype."""

from __future__ import annotations

from typing import Any

from agent33.agents.archetypes.base import AgentArchetype


class AssistantArchetype(AgentArchetype):
    """RAG-integrated conversational assistant.

    Pre-configured with knowledge retrieval capabilities,
    RAG skills, and conversational constraints.
    """

    archetype_name: str = "assistant"
    description: str = "RAG-integrated conversational assistant"
    default_role: str = (
        "You are a helpful assistant with access to a knowledge base. "
        "Use retrieval tools to find relevant information before "
        "answering. Always cite your sources and acknowledge "
        "uncertainty."
    )
    default_capabilities: list[str] = [
        "knowledge_retrieval",
        "text_generation",
        "summarization",
    ]
    default_tools: list[str] = [
        "memory_search",
        "web_fetch",
    ]
    default_constraints: list[str] = [
        "Always search memory before answering factual questions",
        "Cite sources when using retrieved information",
        "Acknowledge when information may be outdated",
    ]

    def create(self, name: str, **overrides: Any) -> dict[str, Any]:
        """Create an assistant agent definition."""
        return self._build_definition(name, **overrides)
