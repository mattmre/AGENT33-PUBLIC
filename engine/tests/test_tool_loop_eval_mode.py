"""Tests for ToolLoop evaluation mode context window enforcement (POST-2.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig
from agent33.llm.base import ChatMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_messages(roles_and_content: list[tuple[str, str]]) -> list[ChatMessage]:
    return [ChatMessage(role=r, content=c) for r, c in roles_and_content]


@pytest.fixture
def loop() -> ToolLoop:
    return ToolLoop(
        router=MagicMock(),
        tool_registry=MagicMock(),
        config=ToolLoopConfig(evaluation_mode=True, max_iterations=5),
        model_context_window=1000,
    )


# ---------------------------------------------------------------------------
# _evict_for_context_budget tests
# ---------------------------------------------------------------------------


class TestEvaluationModeContextEviction:
    """_evict_for_context_budget must trim oldest non-system messages."""

    def test_no_eviction_when_under_budget(self, loop: ToolLoop) -> None:
        messages = _make_messages(
            [
                ("system", "You are an assistant"),
                ("user", "hello"),
                ("assistant", "hi"),
            ]
        )
        original_len = len(messages)
        loop._evict_for_context_budget(messages, budget_tokens=10_000)
        assert len(messages) == original_len

    def test_evicts_oldest_non_system(self, loop: ToolLoop) -> None:
        # Create messages that are clearly over budget
        long_content = "word " * 500  # ~500 words * 1.3 = 650 tokens each
        messages = _make_messages(
            [
                ("system", "short"),
                ("user", long_content),
                ("assistant", long_content),
                ("user", long_content),
                ("assistant", "recent short response"),
            ]
        )
        # Budget of 200 tokens -- should evict oldest non-system messages
        loop._evict_for_context_budget(messages, budget_tokens=200)
        # System message must not be evicted
        assert messages[0].role == "system"
        assert messages[0].content == "short"
        # Should have fewer messages than we started with
        assert len(messages) < 5
        # Remaining non-system messages should be >= 2 (the minimum)
        non_system = [m for m in messages if m.role != "system"]
        assert len(non_system) >= 2

    def test_keeps_minimum_two_non_system(self, loop: ToolLoop) -> None:
        long_content = "word " * 2000
        messages = _make_messages(
            [
                ("system", "sys"),
                ("user", long_content),
                ("assistant", long_content),
            ]
        )
        # Tiny budget -- should NOT evict below 2 non-system messages
        loop._evict_for_context_budget(messages, budget_tokens=1)
        non_system = [m for m in messages if m.role != "system"]
        assert len(non_system) == 2

    def test_preserves_most_recent_messages(self, loop: ToolLoop) -> None:
        """When evicting, the OLDEST non-system messages go first, not the newest."""
        messages = _make_messages(
            [
                ("system", "sys prompt"),
                ("user", "word " * 300),  # old -- evict candidate
                ("assistant", "word " * 300),  # old -- evict candidate
                ("user", "word " * 300),  # old -- evict candidate
                ("assistant", "final answer here"),  # newest -- keep
            ]
        )
        loop._evict_for_context_budget(messages, budget_tokens=100)
        # The "final answer here" assistant message should be preserved
        assert any("final answer here" in (m.content or "") for m in messages)

    def test_system_messages_never_evicted_even_when_large(self, loop: ToolLoop) -> None:
        """System messages are never removed regardless of size."""
        large_system = "word " * 5000  # very large system prompt
        messages = _make_messages(
            [
                ("system", large_system),
                ("user", "hello"),
                ("assistant", "hi"),
            ]
        )
        loop._evict_for_context_budget(messages, budget_tokens=10)
        # System message must still be present
        assert messages[0].role == "system"
        assert messages[0].content == large_system

    def test_handles_list_content(self, loop: ToolLoop) -> None:
        """Content that is a list (multipart) should be handled by the estimator."""
        messages = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content=[{"text": "hello world"}]),  # type: ignore[arg-type]
            ChatMessage(role="assistant", content="ok"),
        ]
        # Should not raise
        loop._evict_for_context_budget(messages, budget_tokens=10_000)
        assert len(messages) == 3


# ---------------------------------------------------------------------------
# ToolLoopConfig.evaluation_mode default
# ---------------------------------------------------------------------------


class TestToolLoopConfigEvaluationMode:
    def test_default_is_false(self) -> None:
        config = ToolLoopConfig()
        assert config.evaluation_mode is False

    def test_can_be_set_true(self) -> None:
        config = ToolLoopConfig(evaluation_mode=True)
        assert config.evaluation_mode is True


# ---------------------------------------------------------------------------
# AgentRuntime evaluation_mode integration
# ---------------------------------------------------------------------------


class TestAgentRuntimeEvaluationMode:
    """AgentRuntime must accept evaluation_mode and pass it to ToolLoopConfig."""

    def test_evaluation_mode_flag_accepted(self) -> None:
        from agent33.agents.definition import AgentDefinition
        from agent33.agents.runtime import AgentRuntime

        definition = MagicMock(spec=AgentDefinition)
        definition.name = "test-agent"
        definition.version = "1.0.0"
        definition.role = "worker"
        definition.capabilities = []
        definition.skills = []
        definition.constraints = MagicMock()
        definition.constraints.max_tokens = 4096
        definition.constraints.timeout_seconds = 60
        definition.constraints.max_retries = 1
        definition.constraints.parallel_allowed = False
        definition.prompts = MagicMock()
        definition.prompts.system = "You are helpful"
        definition.metadata = MagicMock()
        definition.metadata.tags = []

        # Should not raise
        runtime = AgentRuntime(
            definition=definition,
            router=MagicMock(),
            evaluation_mode=True,
        )
        assert runtime._evaluation_mode is True

    def test_evaluation_mode_defaults_false(self) -> None:
        from agent33.agents.definition import AgentDefinition
        from agent33.agents.runtime import AgentRuntime

        definition = MagicMock(spec=AgentDefinition)
        definition.name = "test-agent"
        definition.version = "1.0.0"
        definition.role = "worker"
        definition.capabilities = []
        definition.skills = []
        definition.constraints = MagicMock()
        definition.constraints.max_tokens = 4096
        definition.constraints.timeout_seconds = 60
        definition.constraints.max_retries = 1
        definition.constraints.parallel_allowed = False
        definition.prompts = MagicMock()
        definition.prompts.system = "You are helpful"
        definition.metadata = MagicMock()
        definition.metadata.tags = []

        runtime = AgentRuntime(
            definition=definition,
            router=MagicMock(),
        )
        assert runtime._evaluation_mode is False

    @pytest.mark.asyncio
    async def test_evaluation_mode_suppresses_observation_capture(self) -> None:
        """In evaluation mode, observation_capture should NOT be called."""
        from agent33.agents.definition import AgentDefinition
        from agent33.agents.runtime import AgentRuntime
        from agent33.llm.base import LLMResponse

        definition = MagicMock(spec=AgentDefinition)
        definition.name = "test-agent"
        definition.version = "1.0.0"
        definition.role = MagicMock()
        definition.role.value = "worker"
        definition.agent_id = ""
        definition.description = ""
        definition.capabilities = []
        definition.spec_capabilities = []
        definition.governance = MagicMock()
        definition.governance.scope = None
        definition.governance.commands = None
        definition.governance.network = None
        definition.governance.approval_required = []
        definition.governance.tool_policies = {}
        definition.autonomy_level = MagicMock()
        definition.autonomy_level.value = "full"
        definition.ownership = MagicMock()
        definition.ownership.owner = None
        definition.ownership.escalation_target = None
        definition.dependencies = []
        definition.inputs = {}
        definition.outputs = {}
        definition.constraints = MagicMock()
        definition.constraints.max_tokens = 4096
        definition.constraints.timeout_seconds = 60
        definition.constraints.max_retries = 0
        definition.constraints.parallel_allowed = False
        definition.skills = []

        obs_capture = AsyncMock()
        tool_registry = MagicMock()
        tool_registry.list_all.return_value = []
        tool_registry.get_entry.return_value = None

        router = MagicMock()
        router.complete = AsyncMock(
            return_value=LLMResponse(
                content="done",
                model="test",
                prompt_tokens=10,
                completion_tokens=10,
                tool_calls=None,
                finish_reason="stop",
            )
        )

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            tool_registry=tool_registry,
            observation_capture=obs_capture,
            evaluation_mode=True,
        )

        result = await runtime.invoke_iterative(
            inputs={"task": "test"},
            config=ToolLoopConfig(
                max_iterations=1,
                enable_double_confirmation=False,
            ),
        )

        assert result.termination_reason == "completed"
        # observation_capture.record should NOT have been called
        obs_capture.record.assert_not_called()
