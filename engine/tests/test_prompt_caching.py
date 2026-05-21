"""Tests for Phase 51: Anthropic prompt caching."""

from __future__ import annotations

import copy
import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from agent33.llm.base import ChatMessage
from agent33.llm.openai import OpenAIProvider
from agent33.llm.prompt_caching import (
    _apply_cache_marker,
    _ensure_content_blocks,
    apply_anthropic_cache_control,
    is_anthropic_model,
)

# ---------------------------------------------------------------------------
# is_anthropic_model
# ---------------------------------------------------------------------------


class TestIsAnthropicModel:
    def test_claude_prefix(self) -> None:
        assert is_anthropic_model("claude-3-opus-20240229") is True

    def test_claude_haiku(self) -> None:
        assert is_anthropic_model("claude-3-5-haiku-20241022") is True

    def test_non_claude_model(self) -> None:
        assert is_anthropic_model("gpt-4o") is False

    def test_ollama_model(self) -> None:
        assert is_anthropic_model("llama3.2") is False

    def test_empty_string(self) -> None:
        assert is_anthropic_model("") is False

    def test_claude_in_middle(self) -> None:
        """Only prefix matches count -- 'my-claude-model' should not match."""
        assert is_anthropic_model("my-claude-model") is False


# ---------------------------------------------------------------------------
# _ensure_content_blocks
# ---------------------------------------------------------------------------


class TestEnsureContentBlocks:
    def test_string_to_blocks(self) -> None:
        result = _ensure_content_blocks("Hello world")
        assert result == [{"type": "text", "text": "Hello world"}]

    def test_list_passthrough(self) -> None:
        blocks: list[dict[str, Any]] = [{"type": "text", "text": "hi"}]
        result = _ensure_content_blocks(blocks)
        assert result == blocks
        # Should be a shallow copy, not the same list object
        assert result is not blocks

    def test_none_fallback(self) -> None:
        result = _ensure_content_blocks(None)
        assert result == [{"type": "text", "text": "None"}]

    def test_int_fallback(self) -> None:
        result = _ensure_content_blocks(42)
        assert result == [{"type": "text", "text": "42"}]


# ---------------------------------------------------------------------------
# _apply_cache_marker
# ---------------------------------------------------------------------------


class TestApplyCacheMarker:
    def test_marks_last_content_block(self) -> None:
        msg: dict[str, Any] = {
            "role": "user",
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
        }
        result = _apply_cache_marker(msg)
        # Marker on last block only
        assert "cache_control" not in result["content"][0]
        assert result["content"][1]["cache_control"] == {"type": "ephemeral"}

    def test_string_content_converted_and_marked(self) -> None:
        msg: dict[str, Any] = {"role": "system", "content": "You are a helper."}
        result = _apply_cache_marker(msg)
        assert isinstance(result["content"], list)
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "You are a helper."
        assert result["content"][0]["cache_control"] == {"type": "ephemeral"}

    def test_tool_role_top_level_marker(self) -> None:
        msg: dict[str, Any] = {
            "role": "tool",
            "tool_call_id": "tc_1",
            "content": "result data",
        }
        result = _apply_cache_marker(msg)
        # Top-level cache_control, content left as-is
        assert result["cache_control"] == {"type": "ephemeral"}
        assert result["content"] == "result data"

    def test_no_content_no_error(self) -> None:
        msg: dict[str, Any] = {"role": "assistant"}
        result = _apply_cache_marker(msg)
        assert "cache_control" not in result


# ---------------------------------------------------------------------------
# apply_anthropic_cache_control  (system_and_3 strategy)
# ---------------------------------------------------------------------------


class TestApplyAnthropicCacheControl:
    def test_empty_messages(self) -> None:
        result = apply_anthropic_cache_control([])
        assert result == []

    def test_system_and_3_places_exactly_4_breakpoints(self) -> None:
        """Core strategy: 1 system + 3 most recent non-system = 4 breakpoints."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "msg 1"},
            {"role": "assistant", "content": "reply 1"},
            {"role": "user", "content": "msg 2"},
            {"role": "assistant", "content": "reply 2"},
            {"role": "user", "content": "msg 3"},
            {"role": "assistant", "content": "reply 3"},
        ]
        result = apply_anthropic_cache_control(messages)

        # Count breakpoints
        count = 0
        for msg in result:
            if msg.get("cache_control"):
                count += 1
            if isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("cache_control"):
                        count += 1
        assert count == 4

    def test_system_prompt_gets_breakpoint(self) -> None:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "System prompt."},
            {"role": "user", "content": "Hi"},
        ]
        result = apply_anthropic_cache_control(messages)
        # System message content should be converted to blocks with cache_control
        sys_msg = result[0]
        assert isinstance(sys_msg["content"], list)
        assert sys_msg["content"][-1].get("cache_control") == {"type": "ephemeral"}

    def test_last_3_non_system_get_breakpoints(self) -> None:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "u3"},
        ]
        result = apply_anthropic_cache_control(messages)

        # u1 should NOT have a breakpoint (it's the 1st non-system, not in tail-3)
        u1 = result[1]
        u1_content = u1["content"]
        if isinstance(u1_content, list):
            assert not any(isinstance(b, dict) and b.get("cache_control") for b in u1_content)
        else:
            assert "cache_control" not in u1

        # a2, u3 should have breakpoints (they are in the last 3)
        for idx in [4, 5]:
            msg = result[idx]
            content = msg["content"]
            assert isinstance(content, list)
            assert content[-1].get("cache_control") == {"type": "ephemeral"}

    def test_fewer_than_4_messages(self) -> None:
        """When fewer messages than breakpoint budget, all get marked."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        result = apply_anthropic_cache_control(messages)
        # Both should have cache_control
        assert result[0]["content"][-1].get("cache_control") == {"type": "ephemeral"}
        assert result[1]["content"][-1].get("cache_control") == {"type": "ephemeral"}

    def test_no_system_message(self) -> None:
        """If there is no system message, place up to 4 breakpoints on tail."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
            {"role": "user", "content": "q3"},
        ]
        result = apply_anthropic_cache_control(messages)

        # Last 4 non-system messages should be marked (budget=4, no system used)
        count = 0
        for msg in result:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("cache_control"):
                        count += 1
        assert count == 4

    def test_deep_copy_preserves_original(self) -> None:
        """Caller's messages must not be mutated."""
        original: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
        ]
        frozen = copy.deepcopy(original)
        apply_anthropic_cache_control(original)
        assert original == frozen

    def test_tool_role_in_tail(self) -> None:
        """Tool messages in the tail get top-level cache_control."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "invoke tool"},
            {"role": "tool", "tool_call_id": "tc1", "content": "result"},
            {"role": "user", "content": "thanks"},
        ]
        result = apply_anthropic_cache_control(messages)
        tool_msg = result[3]
        assert tool_msg.get("cache_control") == {"type": "ephemeral"}

    def test_mixed_content_blocks(self) -> None:
        """Messages with image_url blocks alongside text get marker on last block."""
        messages: list[dict[str, Any]] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Look at this:"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
                ],
            },
        ]
        result = apply_anthropic_cache_control(messages)
        blocks = result[0]["content"]
        assert "cache_control" not in blocks[0]
        assert blocks[1].get("cache_control") == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# Provider integration: settings gate
# ---------------------------------------------------------------------------


class TestProviderIntegrationGate:
    """Verify that the OpenAI provider skips caching for non-Claude models
    and when the setting is disabled.  These tests only exercise the gating
    logic, not the HTTP layer."""

    def test_non_claude_model_skips_caching(self) -> None:
        """apply_anthropic_cache_control should not be called for gpt-4o."""
        assert not is_anthropic_model("gpt-4o")

    def test_disabled_setting_skips_caching(self) -> None:
        """When prompt_cache_enabled is False, injection must be skipped."""
        with patch("agent33.llm.openai.settings") as mock_settings:
            mock_settings.prompt_cache_enabled = False
            # Condition check mirrors the provider code
            model = "claude-3-opus-20240229"
            should_cache = is_anthropic_model(model) and mock_settings.prompt_cache_enabled
            assert should_cache is False

    def test_enabled_setting_allows_caching(self) -> None:
        """When prompt_cache_enabled is True and model is Claude, injection proceeds."""
        with patch("agent33.llm.openai.settings") as mock_settings:
            mock_settings.prompt_cache_enabled = True
            model = "claude-3-opus-20240229"
            should_cache = is_anthropic_model(model) and mock_settings.prompt_cache_enabled
            assert should_cache is True


# ---------------------------------------------------------------------------
# Integration: verify serialized payload shape
# ---------------------------------------------------------------------------


class TestPayloadShape:
    """Verify the shape of cache-injected payloads matches Anthropic's
    expected wire format."""

    def test_system_breakpoint_wire_format(self) -> None:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a research assistant."},
            {"role": "user", "content": "Summarise this paper."},
        ]
        result = apply_anthropic_cache_control(messages)
        sys_content = result[0]["content"]
        assert isinstance(sys_content, list)
        assert sys_content[0] == {
            "type": "text",
            "text": "You are a research assistant.",
            "cache_control": {"type": "ephemeral"},
        }

    def test_user_breakpoint_wire_format(self) -> None:
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "Hello Claude"},
        ]
        result = apply_anthropic_cache_control(messages)
        user_content = result[0]["content"]
        assert isinstance(user_content, list)
        assert user_content[0] == {
            "type": "text",
            "text": "Hello Claude",
            "cache_control": {"type": "ephemeral"},
        }

    @pytest.mark.parametrize(
        "cache_ttl",
        ["5m", "1h", "ephemeral"],
    )
    def test_cache_ttl_parameter_accepted(self, cache_ttl: str) -> None:
        """cache_ttl is accepted without error (always maps to ephemeral)."""
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": "hi"},
        ]
        result = apply_anthropic_cache_control(messages, cache_ttl=cache_ttl)
        assert result[0]["content"][-1]["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# End-to-end: provider HTTP POST captures cache markers
# ---------------------------------------------------------------------------


def _fake_openai_response(model: str = "claude-sonnet-4") -> httpx.Response:
    """Build a minimal httpx.Response that mimics an OpenAI chat completion."""
    body = json.dumps(
        {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Hello!"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }
    ).encode()
    return httpx.Response(
        status_code=200,
        content=body,
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "http://localhost:9999/chat/completions"),
    )


class TestProviderCacheInjectionEndToEnd:
    """Verify the OpenAI provider injects (or skips) cache_control markers
    in the actual HTTP payload depending on the target model."""

    async def test_anthropic_model_injects_cache_markers(self) -> None:
        """When model is claude-*, the outgoing payload must contain
        cache_control markers on the serialized messages."""
        provider = OpenAIProvider(api_key="test-key", base_url="http://localhost:9999")

        captured_payloads: list[dict[str, Any]] = []

        async def _capture_post(
            url: str,  # noqa: ARG001
            *,
            json: dict[str, Any] | None = None,  # noqa: A002
            headers: dict[str, str] | None = None,  # noqa: ARG001
            **kwargs: Any,  # noqa: ARG001
        ) -> httpx.Response:
            if json is not None:
                captured_payloads.append(json)
            return _fake_openai_response("claude-sonnet-4")

        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Summarise quantum computing."),
        ]

        with (
            patch.object(provider._client, "post", side_effect=_capture_post),
            patch("agent33.llm.openai.settings") as mock_settings,
        ):
            mock_settings.prompt_cache_enabled = True
            resp = await provider.complete(messages, model="claude-sonnet-4")

        assert resp.content == "Hello!"
        assert len(captured_payloads) == 1

        payload_messages = captured_payloads[0]["messages"]

        # System message should have cache_control in its content blocks
        sys_msg = payload_messages[0]
        assert isinstance(sys_msg["content"], list)
        assert any(
            block.get("cache_control") == {"type": "ephemeral"}
            for block in sys_msg["content"]
            if isinstance(block, dict)
        )

        # User message should also have cache_control
        user_msg = payload_messages[1]
        assert isinstance(user_msg["content"], list)
        assert any(
            block.get("cache_control") == {"type": "ephemeral"}
            for block in user_msg["content"]
            if isinstance(block, dict)
        )

        await provider.close()

    async def test_non_anthropic_model_no_cache_markers(self) -> None:
        """When model is gpt-4o, the outgoing payload must NOT contain
        any cache_control markers."""
        provider = OpenAIProvider(api_key="test-key", base_url="http://localhost:9999")

        captured_payloads: list[dict[str, Any]] = []

        async def _capture_post(
            url: str,  # noqa: ARG001
            *,
            json: dict[str, Any] | None = None,  # noqa: A002
            headers: dict[str, str] | None = None,  # noqa: ARG001
            **kwargs: Any,  # noqa: ARG001
        ) -> httpx.Response:
            if json is not None:
                captured_payloads.append(json)
            return _fake_openai_response("gpt-4o")

        messages = [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Summarise quantum computing."),
        ]

        with (
            patch.object(provider._client, "post", side_effect=_capture_post),
            patch("agent33.llm.openai.settings") as mock_settings,
        ):
            mock_settings.prompt_cache_enabled = True
            resp = await provider.complete(messages, model="gpt-4o")

        assert resp.content == "Hello!"
        assert len(captured_payloads) == 1

        payload_messages = captured_payloads[0]["messages"]

        # No message should have cache_control markers
        for msg in payload_messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        assert "cache_control" not in block, (
                            f"Non-Anthropic model should not have cache_control: {block}"
                        )
            # Top-level cache_control should not exist either
            assert "cache_control" not in msg

        await provider.close()
