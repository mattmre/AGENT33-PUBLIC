"""Tests for Phase 59: Session title generator."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from agent33.agents.title_generator import _clean_title, generate_title
from agent33.llm.base import ChatMessage, LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_router(content: str) -> Any:
    """Create a mock ModelRouter that returns *content*."""
    router = AsyncMock()
    router.complete.return_value = LLMResponse(
        content=content,
        model="test-model",
        prompt_tokens=10,
        completion_tokens=5,
    )
    return router


def _make_failing_router() -> Any:
    """Create a mock ModelRouter that raises on complete()."""
    router = AsyncMock()
    router.complete.side_effect = RuntimeError("model unavailable")
    return router


# ---------------------------------------------------------------------------
# _clean_title unit tests
# ---------------------------------------------------------------------------


class TestCleanTitle:
    def test_strips_whitespace(self) -> None:
        assert _clean_title("  Code Review Assistant  ") == "Code Review Assistant"

    def test_removes_surrounding_double_quotes(self) -> None:
        assert _clean_title('"Code Review Assistant"') == "Code Review Assistant"

    def test_removes_surrounding_single_quotes(self) -> None:
        assert _clean_title("'Code Review Assistant'") == "Code Review Assistant"

    def test_returns_none_for_empty_string(self) -> None:
        assert _clean_title("") is None

    def test_returns_none_for_whitespace_only(self) -> None:
        assert _clean_title("   ") is None

    def test_returns_none_for_too_many_words(self) -> None:
        long = " ".join(f"word{i}" for i in range(15))
        assert _clean_title(long) is None

    def test_takes_first_line_on_multiline(self) -> None:
        result = _clean_title("First Line Title\nSecond line extra stuff")
        assert result == "First Line Title"

    def test_multiline_first_line_too_long(self) -> None:
        long_first = " ".join(f"w{i}" for i in range(15))
        result = _clean_title(f"{long_first}\nShort second")
        assert result is None

    def test_three_word_title(self) -> None:
        assert _clean_title("Code Review Bot") == "Code Review Bot"

    def test_seven_word_title(self) -> None:
        title = "Automated Testing for Web API Endpoints"
        assert _clean_title(title) == title


# ---------------------------------------------------------------------------
# generate_title async tests
# ---------------------------------------------------------------------------


class TestGenerateTitle:
    async def test_returns_title_from_router(self) -> None:
        router = _make_router("Bug Fix Discussion")
        result = await generate_title("Fix the login bug", "I'll look into it", router)
        assert result == "Bug Fix Discussion"

    async def test_uses_provided_model(self) -> None:
        router = _make_router("API Design Help")
        await generate_title("Help with API", "Sure", router, model="gpt-4o-mini")
        # Verify the model was passed to the router.
        call_kwargs = router.complete.call_args
        assert call_kwargs.kwargs["model"] == "gpt-4o-mini"

    async def test_default_model_is_llama32(self) -> None:
        router = _make_router("Test Title")
        await generate_title("Hello", "Hi", router)
        call_kwargs = router.complete.call_args
        assert call_kwargs.kwargs["model"] == "llama3.2"

    async def test_truncates_long_inputs(self) -> None:
        router = _make_router("Long Input Chat")
        long_msg = "x" * 2000
        await generate_title(long_msg, long_msg, router)
        # Extract the user message content from the call.
        call_args = router.complete.call_args
        messages: list[ChatMessage] = call_args.args[0]
        user_content = messages[1].content
        assert isinstance(user_content, str)
        # Each truncated segment should be at most 500 chars.
        # The format is "User: {truncated}\n\nAssistant: {truncated}"
        assert len(user_content) < 1200  # 500 + 500 + labels + separators

    async def test_returns_none_on_router_failure(self) -> None:
        router = _make_failing_router()
        result = await generate_title("Hello", "Hi", router)
        assert result is None

    async def test_returns_none_on_bad_output(self) -> None:
        # Model returns a very long rambling response instead of a title.
        long_output = " ".join(f"word{i}" for i in range(50))
        router = _make_router(long_output)
        result = await generate_title("Hello", "Hi", router)
        assert result is None

    async def test_system_prompt_contains_title_instruction(self) -> None:
        router = _make_router("Test Title")
        await generate_title("Hello", "Hi", router)
        call_args = router.complete.call_args
        messages: list[ChatMessage] = call_args.args[0]
        system_msg = messages[0]
        assert system_msg.role == "system"
        assert isinstance(system_msg.content, str)
        assert "3-7 word title" in system_msg.content

    async def test_low_temperature_for_consistency(self) -> None:
        router = _make_router("Consistent Title")
        await generate_title("Hello", "Hi", router)
        call_kwargs = router.complete.call_args
        assert call_kwargs.kwargs["temperature"] == pytest.approx(0.3)

    async def test_max_tokens_is_small(self) -> None:
        router = _make_router("Short Title")
        await generate_title("Hello", "Hi", router)
        call_kwargs = router.complete.call_args
        assert call_kwargs.kwargs["max_tokens"] == 30

    async def test_strips_quotes_from_output(self) -> None:
        router = _make_router('"Quoted Title Output"')
        result = await generate_title("Hello", "Hi", router)
        assert result == "Quoted Title Output"
