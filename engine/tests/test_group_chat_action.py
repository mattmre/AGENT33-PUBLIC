"""Tests for Phase 41 GroupChat workflow action."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from agent33.workflows.actions.group_chat import (
    GroupChatConfig,
    _build_local_messages,
    execute,
)
from agent33.workflows.actions.speaker_selection import (
    AutoSelector,
    MentionSelector,
    RandomSelector,
    RoundRobinSelector,
    get_selector,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakePrompts:
    """Minimal stand-in for AgentPrompts."""

    def __init__(self, system: str = "") -> None:
        self.system = system


class _FakeAgentDef:
    """Minimal stand-in for AgentDefinition in tests."""

    def __init__(
        self,
        name: str,
        description: str = "",
        system_prompt: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.prompts = _FakePrompts(system_prompt)


def _make_registry(agents: list[_FakeAgentDef]) -> MagicMock:
    """Build a mock agent registry that responds to .get(name)."""
    registry = MagicMock()
    lookup = {a.name: a for a in agents}
    registry.get = MagicMock(side_effect=lambda n: lookup.get(n))
    return registry


def _make_router(responses: list[str]) -> AsyncMock:
    """Build a mock model router returning canned responses in order."""
    router = AsyncMock()
    idx = {"i": 0}

    async def _complete(messages: Any, **kwargs: Any) -> Any:
        content = responses[idx["i"] % len(responses)]
        idx["i"] += 1
        return MagicMock(content=content)

    router.complete = AsyncMock(side_effect=_complete)
    return router


# ===========================================================================
# Speaker selection tests
# ===========================================================================


class TestRoundRobinSelector:
    def test_cycles_through_agents(self) -> None:
        sel = RoundRobinSelector(["alice", "bob", "carol"])
        history: list[dict[str, str]] = []
        assert sel.select(history) == "alice"
        assert sel.select(history) == "bob"
        assert sel.select(history) == "carol"
        assert sel.select(history) == "alice"

    def test_single_agent(self) -> None:
        sel = RoundRobinSelector(["solo"])
        assert sel.select([]) == "solo"
        assert sel.select([]) == "solo"


class TestRandomSelector:
    def test_returns_valid_agent_name(self) -> None:
        names = ["alice", "bob", "carol"]
        sel = RandomSelector(names)
        for _ in range(20):
            assert sel.select([]) in names


class TestMentionSelector:
    def test_finds_mention(self) -> None:
        sel = MentionSelector(["alice", "bob"])
        history = [{"role": "assistant", "content": "I think @bob should answer"}]
        assert sel.select(history) == "bob"

    def test_fallback_to_round_robin(self) -> None:
        sel = MentionSelector(["alice", "bob"])
        history = [{"role": "assistant", "content": "no mentions here"}]
        assert sel.select(history) == "alice"
        assert sel.select(history) == "bob"

    def test_empty_history_returns_first(self) -> None:
        sel = MentionSelector(["alice", "bob"])
        assert sel.select([]) == "alice"


class TestAutoSelector:
    def test_mention_takes_priority(self) -> None:
        sel = AutoSelector(["alice", "bob", "carol"])
        history = [{"role": "assistant", "content": "Ask @carol about this"}]
        assert sel.select(history) == "carol"

    def test_fallback_to_round_robin(self) -> None:
        sel = AutoSelector(["alice", "bob"])
        assert sel.select([]) == "alice"
        assert sel.select([]) == "bob"
        assert sel.select([]) == "alice"


class TestGetSelectorFactory:
    def test_returns_correct_types(self) -> None:
        assert isinstance(get_selector("round_robin", ["a"]), RoundRobinSelector)
        assert isinstance(get_selector("random", ["a"]), RandomSelector)
        assert isinstance(get_selector("mention", ["a"]), MentionSelector)
        assert isinstance(get_selector("auto", ["a"]), AutoSelector)

    def test_unknown_strategy_defaults_to_round_robin(self) -> None:
        sel = get_selector("unknown_strategy", ["a", "b"])
        assert isinstance(sel, RoundRobinSelector)


# ===========================================================================
# GroupChatConfig validation
# ===========================================================================


class TestGroupChatConfigValidation:
    def test_valid_config(self) -> None:
        cfg = GroupChatConfig(
            agents=["alice", "bob"],
            topic="Discuss testing",
        )
        assert cfg.max_rounds == 10
        assert cfg.speaker_selection == "round_robin"
        assert cfg.termination_phrase == "TERMINATE"
        assert cfg.message_history_limit == 20

    def test_max_rounds_bounds(self) -> None:
        with pytest.raises(ValidationError):
            GroupChatConfig(agents=["a"], topic="t", max_rounds=0)
        with pytest.raises(ValidationError):
            GroupChatConfig(agents=["a"], topic="t", max_rounds=101)

    def test_message_history_limit_min(self) -> None:
        with pytest.raises(ValidationError):
            GroupChatConfig(agents=["a"], topic="t", message_history_limit=0)

    def test_requires_agents_and_topic(self) -> None:
        with pytest.raises(ValidationError):
            GroupChatConfig(topic="t")  # type: ignore[call-arg]
        with pytest.raises(ValidationError):
            GroupChatConfig(agents=["a"])  # type: ignore[call-arg]


# ===========================================================================
# GroupChat execution tests
# ===========================================================================


class TestGroupChatMissingDependencies:
    async def test_missing_registry(self) -> None:
        config = GroupChatConfig(agents=["a", "b"], topic="hi")
        result = await execute(config, {})
        assert result["termination_reason"] == "missing_dependencies"

    async def test_missing_router(self) -> None:
        config = GroupChatConfig(agents=["a", "b"], topic="hi")
        result = await execute(config, {"agent_registry": MagicMock()})
        assert result["termination_reason"] == "missing_dependencies"


class TestGroupChatInsufficientAgents:
    async def test_less_than_two_agents(self) -> None:
        registry = _make_registry([_FakeAgentDef("alice", system_prompt="I am Alice")])
        router = _make_router(["hello"])
        config = GroupChatConfig(agents=["alice", "missing"], topic="discuss")
        result = await execute(
            config,
            {
                "agent_registry": registry,
                "model_router": router,
            },
        )
        assert result["termination_reason"] == "insufficient_agents"
        assert result["participating_agents"] == ["alice"]

    async def test_no_agents_found(self) -> None:
        registry = _make_registry([])
        router = _make_router(["hello"])
        config = GroupChatConfig(agents=["x", "y"], topic="discuss")
        result = await execute(
            config,
            {
                "agent_registry": registry,
                "model_router": router,
            },
        )
        assert result["termination_reason"] == "insufficient_agents"


class TestGroupChatBasicConversation:
    async def test_full_conversation(self) -> None:
        agents = [
            _FakeAgentDef("alice", system_prompt="I am Alice"),
            _FakeAgentDef("bob", system_prompt="I am Bob"),
        ]
        registry = _make_registry(agents)
        router = _make_router(["Alice's reply", "Bob's reply"])

        config = GroupChatConfig(
            agents=["alice", "bob"],
            topic="Discuss testing",
            max_rounds=4,
        )
        result = await execute(
            config,
            {
                "agent_registry": registry,
                "model_router": router,
            },
        )

        assert result["termination_reason"] == "max_rounds"
        assert result["rounds_completed"] == 4
        assert len(result["transcript"]) == 4
        assert set(result["participating_agents"]) == {"alice", "bob"}

        # Round-robin: alice, bob, alice, bob
        speakers = [m["speaker"] for m in result["transcript"]]
        assert speakers == ["alice", "bob", "alice", "bob"]


class TestGroupChatTerminationPhrase:
    async def test_terminates_on_phrase(self) -> None:
        agents = [
            _FakeAgentDef("alice", system_prompt="I am Alice"),
            _FakeAgentDef("bob", system_prompt="I am Bob"),
        ]
        registry = _make_registry(agents)
        # Bob says TERMINATE on his first turn (round 2)
        router = _make_router(["thinking...", "I agree. TERMINATE"])

        config = GroupChatConfig(
            agents=["alice", "bob"],
            topic="Quick chat",
            max_rounds=10,
        )
        result = await execute(
            config,
            {
                "agent_registry": registry,
                "model_router": router,
            },
        )

        assert result["termination_reason"] == "termination_phrase"
        assert result["rounds_completed"] == 2
        assert len(result["transcript"]) == 2
        assert "TERMINATE" in result["final_message"]


class TestGroupChatMessageHistoryLimit:
    async def test_sliding_window(self) -> None:
        agents = [
            _FakeAgentDef("alice", system_prompt="Alice"),
            _FakeAgentDef("bob", system_prompt="Bob"),
        ]
        registry = _make_registry(agents)
        router = _make_router(["reply"])

        config = GroupChatConfig(
            agents=["alice", "bob"],
            topic="Chat",
            max_rounds=6,
            message_history_limit=3,
        )
        result = await execute(
            config,
            {
                "agent_registry": registry,
                "model_router": router,
            },
        )

        assert result["rounds_completed"] == 6

        # Verify the router was called and messages passed were windowed.
        # We check that calls were made with message lists whose user/assistant
        # messages (excluding system) don't exceed the limit.
        for call in router.complete.call_args_list:
            msgs = call[0][0]  # first positional arg = messages list
            # Subtract 1 for the system message
            non_system = [m for m in msgs if m.role != "system"]
            assert len(non_system) <= config.message_history_limit


# ===========================================================================
# _build_local_messages tests
# ===========================================================================


class TestBuildLocalMessages:
    def test_own_messages_become_assistant(self) -> None:
        history = [
            {"role": "user", "content": "topic"},
            {"role": "assistant", "content": "[alice]: my answer"},
        ]
        local = _build_local_messages("alice", history, 20)
        assert local[0] == {"role": "user", "content": "topic"}
        assert local[1] == {"role": "assistant", "content": "my answer"}

    def test_other_messages_become_user(self) -> None:
        history = [
            {"role": "user", "content": "topic"},
            {"role": "assistant", "content": "[bob]: bob's answer"},
        ]
        local = _build_local_messages("alice", history, 20)
        assert local[0] == {"role": "user", "content": "topic"}
        assert local[1] == {"role": "user", "content": "[bob]: bob's answer"}

    def test_window_limit(self) -> None:
        history = [{"role": "user", "content": f"msg-{i}"} for i in range(10)]
        local = _build_local_messages("alice", history, 3)
        assert len(local) == 3
        assert local[0]["content"] == "msg-7"

    def test_empty_history(self) -> None:
        assert _build_local_messages("alice", [], 5) == []
