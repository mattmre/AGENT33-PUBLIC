"""Tests for Phase 40 agent archetype system."""

from __future__ import annotations

import pytest

from agent33.agents.archetypes import (
    ArchetypeRegistry,
    AssistantArchetype,
    CoderArchetype,
    GroupChatHostArchetype,
    RouterArchetype,
)

ALL_ARCHETYPES = [
    AssistantArchetype(),
    CoderArchetype(),
    RouterArchetype(),
    GroupChatHostArchetype(),
]


@pytest.fixture()
def registry() -> ArchetypeRegistry:
    reg = ArchetypeRegistry()
    for arch in ALL_ARCHETYPES:
        reg.register(arch)
    return reg


class TestArchetypeRegistry:
    def test_register_and_get(self) -> None:
        reg = ArchetypeRegistry()
        arch = AssistantArchetype()
        reg.register(arch)
        assert reg.get("assistant") is arch

    def test_get_returns_none_for_unknown(self) -> None:
        reg = ArchetypeRegistry()
        assert reg.get("nonexistent") is None

    def test_list_all(self, registry: ArchetypeRegistry) -> None:
        all_archetypes = registry.list_all()
        assert len(all_archetypes) == 4
        names = {a.archetype_name for a in all_archetypes}
        assert names == {"assistant", "coder", "router", "group-chat-host"}

    def test_create_agent_unknown_raises(self) -> None:
        reg = ArchetypeRegistry()
        with pytest.raises(ValueError, match="Unknown archetype"):
            reg.create_agent("nonexistent", "my-agent")

    def test_create_agent_delegates(self, registry: ArchetypeRegistry) -> None:
        defn = registry.create_agent("coder", "my-coder")
        assert defn["name"] == "my-coder"
        assert defn["archetype"] == "coder"


class TestAssistantArchetype:
    def test_defaults(self) -> None:
        arch = AssistantArchetype()
        defn = arch.create("my-assistant")
        assert defn["name"] == "my-assistant"
        assert defn["archetype"] == "assistant"
        assert "knowledge_retrieval" in defn["capabilities"]
        assert "text_generation" in defn["capabilities"]
        assert "summarization" in defn["capabilities"]
        assert "memory_search" in defn["tools"]
        assert "web_fetch" in defn["tools"]
        assert len(defn["constraints"]) == 3
        assert "role" in defn


class TestCoderArchetype:
    def test_defaults(self) -> None:
        arch = CoderArchetype()
        defn = arch.create("my-coder")
        assert defn["name"] == "my-coder"
        assert defn["archetype"] == "coder"
        assert "code_generation" in defn["capabilities"]
        assert "code_execution" in defn["capabilities"]
        assert "file_operations" in defn["capabilities"]
        assert "file_read" in defn["tools"]
        assert "file_write" in defn["tools"]
        assert "shell" in defn["tools"]
        assert len(defn["constraints"]) == 3


class TestRouterArchetype:
    def test_defaults(self) -> None:
        arch = RouterArchetype()
        defn = arch.create("my-router")
        assert defn["name"] == "my-router"
        assert defn["archetype"] == "router"
        assert "orchestration" in defn["capabilities"]
        assert "classification" in defn["capabilities"]
        assert defn["tools"] == []

    def test_role_override(self) -> None:
        arch = RouterArchetype()
        defn = arch.create("my-router", role="Custom router role")
        assert defn["role"] == "Custom router role"
        assert defn["archetype"] == "router"
        assert "orchestration" in defn["capabilities"]


class TestGroupChatHostArchetype:
    def test_defaults(self) -> None:
        arch = GroupChatHostArchetype()
        defn = arch.create("my-host")
        assert defn["name"] == "my-host"
        assert defn["archetype"] == "group-chat-host"
        assert "orchestration" in defn["capabilities"]
        assert "communication" in defn["capabilities"]
        assert "summarization" in defn["capabilities"]
        assert defn["tools"] == []
        assert len(defn["constraints"]) == 3


class TestOverrides:
    def test_extra_tools_extends_defaults(self) -> None:
        arch = CoderArchetype()
        defn = arch.create("ext-coder", extra_tools=["docker", "git"])
        assert "file_read" in defn["tools"]
        assert "docker" in defn["tools"]
        assert "git" in defn["tools"]
        assert len(defn["tools"]) == 5

    def test_tools_override_replaces_defaults(self) -> None:
        arch = CoderArchetype()
        defn = arch.create("custom-coder", tools=["only-this"])
        assert defn["tools"] == ["only-this"]

    def test_arbitrary_overrides_passed_through(self) -> None:
        arch = AssistantArchetype()
        defn = arch.create(
            "tagged-assistant",
            temperature=0.7,
            max_tokens=2048,
        )
        assert defn["temperature"] == 0.7
        assert defn["max_tokens"] == 2048

    def test_capabilities_override(self) -> None:
        arch = AssistantArchetype()
        defn = arch.create("custom-caps", capabilities=["only_this"])
        assert defn["capabilities"] == ["only_this"]

    def test_constraints_override(self) -> None:
        arch = RouterArchetype()
        defn = arch.create(
            "custom-constraints",
            constraints=["single constraint"],
        )
        assert defn["constraints"] == ["single constraint"]


class TestCrossArchetype:
    def test_all_archetypes_have_unique_names(self) -> None:
        names = [a.archetype_name for a in ALL_ARCHETYPES]
        assert len(names) == len(set(names))

    def test_register_builtins(self) -> None:
        reg = ArchetypeRegistry()
        for arch in ALL_ARCHETYPES:
            reg.register(arch)
        assert len(reg.list_all()) == 4
        assert reg.get("assistant") is not None
        assert reg.get("coder") is not None
        assert reg.get("router") is not None
        assert reg.get("group-chat-host") is not None


class TestFullWorkflow:
    def test_full_workflow(self) -> None:
        registry = ArchetypeRegistry()
        registry.register(AssistantArchetype())
        registry.register(CoderArchetype())
        assert len(registry.list_all()) == 2

        defn = registry.create_agent("assistant", "my-helper", role="Custom role")
        assert defn["name"] == "my-helper"
        assert defn["role"] == "Custom role"
        assert defn["archetype"] == "assistant"
        assert "knowledge_retrieval" in defn["capabilities"]
