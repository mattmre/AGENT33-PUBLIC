"""Agent archetype system — pre-built templates for common agent patterns."""

from agent33.agents.archetypes.assistant import AssistantArchetype
from agent33.agents.archetypes.base import AgentArchetype, ArchetypeRegistry
from agent33.agents.archetypes.coder import CoderArchetype
from agent33.agents.archetypes.group_chat_host import GroupChatHostArchetype
from agent33.agents.archetypes.router import RouterArchetype

__all__ = [
    "AgentArchetype",
    "ArchetypeRegistry",
    "AssistantArchetype",
    "CoderArchetype",
    "GroupChatHostArchetype",
    "RouterArchetype",
]
