"""Tests for context window management.

Covers token estimation, ContextBudget, ContextSnapshot, ContextManager
(snapshot, unwind, summarize_and_compact, manage), budget_for_model,
and the fallback summary path.

Every test asserts specific behavioral outcomes -- not just that functions
run without error.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.agents.context_manager import (
    MODEL_CONTEXT_LIMITS,
    ContextBudget,
    ContextManager,
    ContextSnapshot,
    budget_for_model,
    estimate_message_tokens,
    estimate_tokens,
)
from agent33.llm.base import ChatMessage, LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _msg(role: str, content: str) -> ChatMessage:
    return ChatMessage(role=role, content=content)


def _make_router(summary_text: str = "Summary of conversation...") -> MagicMock:
    """Create a mock ModelRouter whose complete() returns the given text."""
    mock_router = MagicMock()
    mock_router.complete = AsyncMock(
        return_value=LLMResponse(
            content=summary_text,
            model="test",
            prompt_tokens=10,
            completion_tokens=5,
        )
    )
    return mock_router


# ═══════════════════════════════════════════════════════════════════════
# Token estimation tests
# ═══════════════════════════════════════════════════════════════════════


class TestEstimateTokens:
    """estimate_tokens() character-based heuristic."""

    def test_empty_string_returns_zero(self) -> None:
        assert estimate_tokens("") == 0

    def test_short_text_returns_reasonable_estimate(self) -> None:
        # "Hello" is 5 chars. At default 3.5 chars/token => 5/3.5 ≈ 1.43 => int(1.43)=1
        result = estimate_tokens("Hello")
        assert result == 1
        # "Hello world" is 11 chars => 11/3.5 ≈ 3.14 => 3
        result2 = estimate_tokens("Hello world")
        assert result2 == 3

    def test_long_text_scales_linearly(self) -> None:
        short = "a" * 100
        long = "a" * 1000
        tokens_short = estimate_tokens(short)
        tokens_long = estimate_tokens(long)
        # Should be ~10x as many tokens
        ratio = tokens_long / tokens_short
        assert 9.5 <= ratio <= 10.5, f"Expected ~10x scaling, got {ratio}"

    def test_estimate_message_tokens_adds_per_message_overhead(self) -> None:
        text = "Hello world"
        raw_tokens = estimate_tokens(text)
        messages = [_msg("user", text)]
        msg_tokens = estimate_message_tokens(messages)
        # Each message adds 4 tokens overhead
        assert msg_tokens == raw_tokens + 4

        # Two messages doubles the overhead
        messages2 = [_msg("user", text), _msg("assistant", text)]
        msg_tokens2 = estimate_message_tokens(messages2)
        assert msg_tokens2 == (raw_tokens + 4) * 2

    def test_custom_chars_per_token_ratio(self) -> None:
        text = "a" * 100
        default_tokens = estimate_tokens(text)  # 100 / 3.5 ≈ 28
        custom_tokens = estimate_tokens(text, chars_per_token=5.0)  # 100 / 5 = 20
        assert custom_tokens == 20
        assert default_tokens == 28
        assert custom_tokens < default_tokens


# ═══════════════════════════════════════════════════════════════════════
# ContextBudget tests
# ═══════════════════════════════════════════════════════════════════════


class TestContextBudget:
    """ContextBudget dataclass properties."""

    def test_defaults_are_sensible(self) -> None:
        budget = ContextBudget()
        assert budget.max_context_tokens == 128_000
        assert budget.reserved_for_completion == 4_096
        assert budget.summarize_threshold == 0.75

    def test_effective_limit_subtracts_reserved(self) -> None:
        budget = ContextBudget(max_context_tokens=10_000, reserved_for_completion=1_000)
        assert budget.effective_limit == 9_000

    def test_summarize_at_is_fraction_of_effective_limit(self) -> None:
        budget = ContextBudget(
            max_context_tokens=10_000,
            reserved_for_completion=2_000,
            summarize_threshold=0.5,
        )
        # effective_limit = 8000, summarize_at = 8000 * 0.5 = 4000
        assert budget.effective_limit == 8_000
        assert budget.summarize_at == 4_000

    def test_custom_values_work(self) -> None:
        budget = ContextBudget(
            max_context_tokens=200_000,
            reserved_for_completion=8_000,
            summarize_threshold=0.9,
        )
        assert budget.max_context_tokens == 200_000
        assert budget.reserved_for_completion == 8_000
        assert budget.summarize_threshold == 0.9
        assert budget.effective_limit == 192_000
        assert budget.summarize_at == int(192_000 * 0.9)


# ═══════════════════════════════════════════════════════════════════════
# ContextSnapshot tests
# ═══════════════════════════════════════════════════════════════════════


class TestContextSnapshot:
    """ContextSnapshot utilization property and field population."""

    def test_utilization_computation(self) -> None:
        budget = ContextBudget(max_context_tokens=10_000, reserved_for_completion=0)
        snap = ContextSnapshot(
            total_tokens=5_000,
            message_count=10,
            budget=budget,
            headroom=5_000,
            needs_summarization=False,
            needs_unwinding=False,
        )
        assert snap.utilization == 0.5

    def test_utilization_with_zero_effective_limit_returns_one(self) -> None:
        budget = ContextBudget(max_context_tokens=1000, reserved_for_completion=1000)
        assert budget.effective_limit == 0
        snap = ContextSnapshot(
            total_tokens=100,
            message_count=2,
            budget=budget,
            headroom=0,
            needs_summarization=True,
            needs_unwinding=True,
        )
        assert snap.utilization == 1.0

    def test_all_fields_populated(self) -> None:
        budget = ContextBudget(max_context_tokens=20_000, reserved_for_completion=2_000)
        snap = ContextSnapshot(
            total_tokens=15_000,
            message_count=42,
            budget=budget,
            headroom=3_000,
            needs_summarization=True,
            needs_unwinding=False,
        )
        assert snap.total_tokens == 15_000
        assert snap.message_count == 42
        assert snap.budget is budget
        assert snap.headroom == 3_000
        assert snap.needs_summarization is True
        assert snap.needs_unwinding is False
        # utilization = 15000 / 18000 ≈ 0.833
        assert abs(snap.utilization - 15_000 / 18_000) < 0.001


# ═══════════════════════════════════════════════════════════════════════
# ContextManager.snapshot() tests
# ═══════════════════════════════════════════════════════════════════════


class TestContextManagerSnapshot:
    """ContextManager.snapshot() produces correct snapshots."""

    def test_under_threshold(self) -> None:
        """Short conversation is well under both thresholds."""
        budget = ContextBudget(
            max_context_tokens=100_000,
            reserved_for_completion=4_000,
            summarize_threshold=0.75,
        )
        cm = ContextManager(budget=budget)
        messages = [_msg("user", "hi")]
        snap = cm.snapshot(messages)

        assert snap.needs_summarization is False
        assert snap.needs_unwinding is False
        assert snap.total_tokens > 0
        assert snap.message_count == 1
        assert snap.headroom > 0

    def test_over_threshold_under_limit(self) -> None:
        """Messages exceed summarize_at but stay under effective_limit."""
        # effective_limit = 100, summarize_at = 50
        budget = ContextBudget(
            max_context_tokens=200,
            reserved_for_completion=100,
            summarize_threshold=0.5,
        )
        cm = ContextManager(budget=budget)
        # Create messages that total ~60-90 tokens (over 50, under 100)
        # Each message = estimate_tokens(content) + 4 overhead
        # "a"*210 at 3.5 chars/tok = 60 tokens + 4 = 64
        messages = [_msg("user", "a" * 210)]
        snap = cm.snapshot(messages)

        assert snap.needs_summarization is True
        assert snap.needs_unwinding is False

    def test_over_limit(self) -> None:
        """Messages exceed effective_limit -- both flags true."""
        budget = ContextBudget(
            max_context_tokens=50,
            reserved_for_completion=10,
            summarize_threshold=0.5,
        )
        cm = ContextManager(budget=budget)
        # effective_limit=40, summarize_at=20
        # "a"*200 at 3.5 chars/tok = 57 tokens + 4 = 61 >> 40
        messages = [_msg("user", "a" * 200)]
        snap = cm.snapshot(messages)

        assert snap.needs_summarization is True
        assert snap.needs_unwinding is True
        assert snap.headroom == 0


# ═══════════════════════════════════════════════════════════════════════
# ContextManager.unwind() tests
# ═══════════════════════════════════════════════════════════════════════


class TestContextManagerUnwind:
    """ContextManager.unwind() removes oldest non-system messages."""

    def _small_budget_cm(self) -> ContextManager:
        """Manager with small effective limit for easy testing."""
        budget = ContextBudget(
            max_context_tokens=200,
            reserved_for_completion=10,
        )
        return ContextManager(budget=budget)

    def test_under_target_returns_all_unchanged(self) -> None:
        cm = self._small_budget_cm()
        messages = [_msg("user", "short")]
        result = cm.unwind(messages)
        assert len(result) == 1
        assert result[0].content == "short"

    def test_over_target_removes_oldest_non_system(self) -> None:
        budget = ContextBudget(max_context_tokens=100, reserved_for_completion=10)
        cm = ContextManager(budget=budget)
        # effective_limit = 90 tokens
        messages = [
            _msg("user", "first " + "a" * 100),
            _msg("assistant", "second " + "b" * 100),
            _msg("user", "third " + "c" * 100),
        ]
        result = cm.unwind(messages)
        # Some messages should have been removed to fit under 90 tokens
        assert len(result) < len(messages)
        # The most recent message should still be present
        assert result[-1].content == messages[-1].content

    def test_system_messages_preserved(self) -> None:
        budget = ContextBudget(max_context_tokens=80, reserved_for_completion=10)
        cm = ContextManager(budget=budget)
        # effective_limit = 70
        messages = [
            _msg("system", "You are helpful."),
            _msg("user", "a" * 200),
            _msg("assistant", "b" * 200),
            _msg("user", "c" * 50),
        ]
        result = cm.unwind(messages)
        # System message must be preserved
        system_msgs = [m for m in result if m.role == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "You are helpful."

    def test_most_recent_messages_kept(self) -> None:
        budget = ContextBudget(max_context_tokens=100, reserved_for_completion=10)
        cm = ContextManager(budget=budget)
        messages = [
            _msg("user", "oldest " + "x" * 100),
            _msg("assistant", "middle " + "y" * 100),
            _msg("user", "newest " + "z" * 10),
        ]
        result = cm.unwind(messages)
        # The newest message should be kept
        non_system = [m for m in result if m.role != "system"]
        assert any("newest" in m.content for m in non_system)

    def test_custom_target_tokens(self) -> None:
        cm = self._small_budget_cm()
        messages = [
            _msg("user", "a" * 100),
            _msg("assistant", "b" * 100),
            _msg("user", "c" * 20),
        ]
        # Use a very small target to force aggressive unwinding
        result = cm.unwind(messages, target_tokens=30)
        # Should have removed messages to fit
        total_after = estimate_message_tokens(result)
        assert total_after <= 30

    def test_all_non_system_removed_if_necessary(self) -> None:
        """If target is tiny, only system messages remain."""
        budget = ContextBudget(max_context_tokens=50, reserved_for_completion=0)
        cm = ContextManager(budget=budget)
        messages = [
            _msg("system", "Be helpful."),
            _msg("user", "a" * 200),
            _msg("assistant", "b" * 200),
        ]
        result = cm.unwind(messages, target_tokens=15)
        # Only system should remain (if system alone fits)
        non_system = [m for m in result if m.role != "system"]
        assert len(non_system) == 0
        assert len(result) >= 1  # system preserved
        assert result[0].role == "system"


# ═══════════════════════════════════════════════════════════════════════
# ContextManager.summarize_and_compact() tests
# ═══════════════════════════════════════════════════════════════════════


class TestSummarizeAndCompact:
    """ContextManager.summarize_and_compact() LLM-based summarization."""

    @pytest.mark.asyncio
    async def test_few_messages_no_change(self) -> None:
        """If non-system messages <= keep_recent, returns messages unchanged."""
        cm = ContextManager()
        messages = [
            _msg("system", "System prompt"),
            _msg("user", "Hello"),
            _msg("assistant", "Hi there"),
        ]
        result = await cm.summarize_and_compact(messages, keep_recent=4)
        assert len(result) == 3
        assert result[0].content == "System prompt"
        assert result[1].content == "Hello"
        assert result[2].content == "Hi there"

    @pytest.mark.asyncio
    async def test_many_messages_compacted_with_summary(self) -> None:
        """Older messages replaced with a single summary message."""
        router = _make_router("LLM summary of older messages.")
        cm = ContextManager(router=router)
        messages = [
            _msg("system", "System prompt"),
            _msg("user", "msg1"),
            _msg("assistant", "msg2"),
            _msg("user", "msg3"),
            _msg("assistant", "msg4"),
            _msg("user", "msg5"),
            _msg("assistant", "msg6"),
        ]
        result = await cm.summarize_and_compact(messages, keep_recent=2)
        # Structure: system + summary + 2 recent
        assert len(result) == 4
        assert result[0].role == "system"
        assert result[0].content == "System prompt"
        # Summary injected after system
        assert "[Context Summary]" in result[1].content
        assert "LLM summary of older messages." in result[1].content
        # Last 2 non-system messages preserved
        assert result[2].content == "msg5"
        assert result[3].content == "msg6"
        # Router was called
        router.complete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_system_preserved_summary_after_system(self) -> None:
        """System messages come first, summary injected after them."""
        router = _make_router("Compressed history.")
        cm = ContextManager(router=router)
        messages = [
            _msg("system", "System A"),
            _msg("system", "System B"),
            _msg("user", "old1"),
            _msg("assistant", "old2"),
            _msg("user", "old3"),
            _msg("assistant", "recent1"),
            _msg("user", "recent2"),
        ]
        result = await cm.summarize_and_compact(messages, keep_recent=2)
        # Both system messages first
        assert result[0].role == "system"
        assert result[0].content == "System A"
        assert result[1].role == "system"
        assert result[1].content == "System B"
        # Summary next
        assert "[Context Summary]" in result[2].content
        # Then recent
        assert result[3].content == "recent1"
        assert result[4].content == "recent2"

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_fallback_summary(self) -> None:
        """If the router raises, fallback summary is used."""
        router = MagicMock()
        router.complete = AsyncMock(side_effect=RuntimeError("LLM down"))
        cm = ContextManager(router=router)
        messages = [
            _msg("system", "System"),
            _msg("user", "old message one"),
            _msg("assistant", "old reply"),
            _msg("user", "old message two"),
            _msg("assistant", "old reply two"),
            _msg("user", "recent question"),
            _msg("assistant", "recent answer"),
        ]
        result = await cm.summarize_and_compact(messages, keep_recent=2)
        # Should still produce a summary (fallback)
        assert len(result) == 4  # system + summary + 2 recent
        assert "[Context Summary]" in result[1].content
        # Fallback summary contains "Prior conversation"
        assert "Prior conversation" in result[1].content
        # Recent messages preserved
        assert result[2].content == "recent question"
        assert result[3].content == "recent answer"

    @pytest.mark.asyncio
    async def test_no_router_uses_fallback(self) -> None:
        """Without a router, the fallback summary is used directly."""
        cm = ContextManager(router=None)
        messages = [
            _msg("system", "System"),
            _msg("user", "old1"),
            _msg("assistant", "old2"),
            _msg("user", "old3"),
            _msg("assistant", "recent1"),
            _msg("user", "recent2"),
        ]
        result = await cm.summarize_and_compact(messages, keep_recent=2)
        assert len(result) == 4
        assert "[Context Summary]" in result[1].content
        assert "Prior conversation" in result[1].content


# ═══════════════════════════════════════════════════════════════════════
# ContextManager.manage() tests
# ═══════════════════════════════════════════════════════════════════════


class TestManage:
    """ContextManager.manage() orchestrates summarization + unwinding."""

    @pytest.mark.asyncio
    async def test_under_threshold_no_change(self) -> None:
        """Messages well under threshold are returned unchanged."""
        budget = ContextBudget(max_context_tokens=100_000, reserved_for_completion=4_000)
        cm = ContextManager(budget=budget)
        messages = [_msg("user", "hi")]
        result = await cm.manage(messages)
        assert len(result) == 1
        assert result[0].content == "hi"

    @pytest.mark.asyncio
    async def test_over_threshold_with_router_calls_summarize(self) -> None:
        """Over threshold but under limit: summarize via router."""
        budget = ContextBudget(
            max_context_tokens=200,
            reserved_for_completion=10,
            summarize_threshold=0.3,  # summarize_at = 190 * 0.3 = 57
        )
        router = _make_router("Compact summary.")
        cm = ContextManager(budget=budget, router=router)
        # Build messages that exceed 57 tokens but stay under 190
        # Each "a"*100 ≈ 28 tokens + 4 overhead = 32. We need >57 total.
        messages = [
            _msg("system", "Be helpful."),
            _msg("user", "a" * 100),
            _msg("assistant", "b" * 100),
            _msg("user", "c" * 50),
            _msg("assistant", "d" * 50),
            _msg("user", "latest question"),
        ]
        result = await cm.manage(messages, keep_recent=2)
        # Router should have been called for summarization
        router.complete.assert_awaited_once()
        # Result should contain summary
        summary_msgs = [m for m in result if "[Context Summary]" in m.content]
        assert len(summary_msgs) == 1

    @pytest.mark.asyncio
    async def test_over_limit_with_router_summarize_then_unwind(self) -> None:
        """Over limit with router: try summarize, then unwind if still over."""
        # Very small budget so even summarized messages might still be over
        budget = ContextBudget(
            max_context_tokens=60,
            reserved_for_completion=5,
            summarize_threshold=0.5,
        )
        # effective_limit = 55, summarize_at = 27
        # Return a large summary that keeps us over the limit
        router = _make_router("x" * 200)  # ~57 tokens, still over limit
        cm = ContextManager(budget=budget, router=router)
        messages = [
            _msg("system", "sys"),
            _msg("user", "a" * 100),
            _msg("assistant", "b" * 100),
            _msg("user", "c" * 100),
            _msg("assistant", "d" * 100),
            _msg("user", "e" * 50),
        ]
        result = await cm.manage(messages, keep_recent=2)
        # Should have attempted summarization
        router.complete.assert_awaited_once()
        # Then unwound to fit under effective_limit
        total = estimate_message_tokens(result)
        assert total <= budget.effective_limit

    @pytest.mark.asyncio
    async def test_over_limit_without_router_unwinds(self) -> None:
        """Over limit without router: hard unwind to effective_limit."""
        budget = ContextBudget(
            max_context_tokens=80,
            reserved_for_completion=10,
            summarize_threshold=0.5,
        )
        cm = ContextManager(budget=budget, router=None)
        # effective_limit = 70
        messages = [
            _msg("system", "sys"),
            _msg("user", "a" * 200),
            _msg("assistant", "b" * 200),
            _msg("user", "recent"),
        ]
        result = await cm.manage(messages)
        total = estimate_message_tokens(result)
        assert total <= budget.effective_limit
        # System message preserved
        assert any(m.role == "system" for m in result)

    @pytest.mark.asyncio
    async def test_over_threshold_without_router_unwinds_to_summarize_at(self) -> None:
        """Over threshold but under limit, no router: unwinds to summarize_at."""
        budget = ContextBudget(
            max_context_tokens=300,
            reserved_for_completion=10,
            summarize_threshold=0.3,
        )
        cm = ContextManager(budget=budget, router=None)
        # effective_limit=290, summarize_at=87
        # Create messages totaling ~100-200 tokens (over 87, under 290)
        messages = [
            _msg("system", "sys"),
            _msg("user", "a" * 100),
            _msg("assistant", "b" * 100),
            _msg("user", "c" * 100),
            _msg("assistant", "recent"),
        ]
        snap_before = cm.snapshot(messages)
        assert snap_before.needs_summarization is True
        assert snap_before.needs_unwinding is False

        result = await cm.manage(messages)
        total_after = estimate_message_tokens(result)
        assert total_after <= budget.summarize_at


# ═══════════════════════════════════════════════════════════════════════
# budget_for_model() tests
# ═══════════════════════════════════════════════════════════════════════


class TestBudgetForModel:
    """budget_for_model() factory function."""

    def test_known_model_returns_correct_limit(self) -> None:
        budget = budget_for_model("gpt-4")
        assert budget.max_context_tokens == 8_192
        budget2 = budget_for_model("claude-3-opus")
        assert budget2.max_context_tokens == 200_000

    def test_unknown_model_returns_128k_default(self) -> None:
        budget = budget_for_model("some-unknown-model-xyz")
        assert budget.max_context_tokens == 128_000

    def test_reserved_for_completion_passed_through(self) -> None:
        budget = budget_for_model("gpt-4", reserved_for_completion=8_000)
        assert budget.reserved_for_completion == 8_000
        assert budget.max_context_tokens == 8_192
        assert budget.effective_limit == 192


# ═══════════════════════════════════════════════════════════════════════
# _fallback_summary tests
# ═══════════════════════════════════════════════════════════════════════


class TestFallbackSummary:
    """ContextManager._fallback_summary() static method."""

    def test_creates_readable_summary(self) -> None:
        messages = [
            _msg("user", "What is Python?"),
            _msg("assistant", "Python is a programming language."),
        ]
        summary = ContextManager._fallback_summary(messages)
        assert "Prior conversation (2 messages):" in summary
        assert "[user]" in summary
        assert "[assistant]" in summary
        assert "What is Python?" in summary

    def test_truncates_at_ten_with_more_note(self) -> None:
        messages = [_msg("user", f"Message number {i}") for i in range(15)]
        summary = ContextManager._fallback_summary(messages)
        assert "Prior conversation (15 messages):" in summary
        # Should have exactly 10 preview lines plus header plus "more" note
        assert "5 more messages" in summary
        # Messages 0-9 should be present, 10-14 should not
        assert "Message number 0" in summary
        assert "Message number 9" in summary
        assert "Message number 10" not in summary


# ═══════════════════════════════════════════════════════════════════════
# MODEL_CONTEXT_LIMITS sanity check
# ═══════════════════════════════════════════════════════════════════════


class TestModelContextLimits:
    """Sanity check that MODEL_CONTEXT_LIMITS is populated correctly."""

    def test_contains_known_models(self) -> None:
        assert "gpt-4o" in MODEL_CONTEXT_LIMITS
        assert "claude-3-opus" in MODEL_CONTEXT_LIMITS
        assert "llama3.2" in MODEL_CONTEXT_LIMITS

    def test_all_values_are_positive_ints(self) -> None:
        for model, limit in MODEL_CONTEXT_LIMITS.items():
            assert isinstance(limit, int), f"{model} limit is not int"
            assert limit > 0, f"{model} limit must be positive"
