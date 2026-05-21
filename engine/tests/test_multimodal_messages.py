"""Tests for multimodal content blocks in ChatMessage.

Covers TextBlock, ImageBlock, AudioBlock creation, the text_content
property, backward compatibility with plain-string content, and
provider serialization for both OpenAI and Ollama formats.
"""

import pytest

from agent33.llm.base import (
    AudioBlock,
    ChatMessage,
    ImageBlock,
    TextBlock,
)
from agent33.llm.ollama import OllamaProvider
from agent33.llm.openai import OpenAIProvider

# ---------------------------------------------------------------------------
# Content block creation
# ---------------------------------------------------------------------------


class TestTextBlock:
    def test_create(self) -> None:
        block = TextBlock(text="hello")
        assert block.text == "hello"

    def test_frozen(self) -> None:
        block = TextBlock(text="hello")
        with pytest.raises(AttributeError):
            block.text = "bye"  # type: ignore[misc]


class TestImageBlock:
    def test_create_with_url(self) -> None:
        block = ImageBlock(url="https://example.com/img.png")
        assert block.url == "https://example.com/img.png"
        assert block.base64_data is None
        assert block.media_type == "image/png"
        assert block.detail == "auto"

    def test_create_with_base64(self) -> None:
        block = ImageBlock(base64_data="aGVsbG8=", media_type="image/jpeg")
        assert block.base64_data == "aGVsbG8="
        assert block.url is None
        assert block.media_type == "image/jpeg"

    def test_frozen(self) -> None:
        block = ImageBlock(url="x")
        with pytest.raises(AttributeError):
            block.url = "y"  # type: ignore[misc]


class TestAudioBlock:
    def test_create(self) -> None:
        block = AudioBlock(url="https://example.com/audio.wav")
        assert block.url == "https://example.com/audio.wav"
        assert block.base64_data is None
        assert block.media_type == "audio/wav"

    def test_create_with_base64(self) -> None:
        block = AudioBlock(base64_data="QUFB", media_type="audio/mp3")
        assert block.base64_data == "QUFB"
        assert block.media_type == "audio/mp3"

    def test_frozen(self) -> None:
        block = AudioBlock(url="x")
        with pytest.raises(AttributeError):
            block.url = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ChatMessage.text_content property
# ---------------------------------------------------------------------------


class TestTextContentProperty:
    def test_str_content_returns_str(self) -> None:
        msg = ChatMessage(role="user", content="plain text")
        assert msg.text_content == "plain text"

    def test_list_content_extracts_text_blocks(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[TextBlock(text="hello"), TextBlock(text="world")],
        )
        assert msg.text_content == "hello world"

    def test_mixed_content_only_returns_text(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[
                TextBlock(text="describe this"),
                ImageBlock(url="https://example.com/img.png"),
                TextBlock(text="image"),
            ],
        )
        assert msg.text_content == "describe this image"

    def test_empty_list_returns_empty_string(self) -> None:
        msg = ChatMessage(role="user", content=[])
        assert msg.text_content == ""

    def test_list_with_no_text_blocks_returns_empty(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[ImageBlock(url="https://example.com/img.png")],
        )
        assert msg.text_content == ""


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_str_content_still_works(self) -> None:
        """Existing code creating ChatMessage with str content must keep working."""
        msg = ChatMessage(role="user", content="hello")
        assert msg.content == "hello"
        assert msg.text_content == "hello"

    def test_str_content_with_optional_fields(self) -> None:
        msg = ChatMessage(role="assistant", content="reply", name="bot")
        assert msg.content == "reply"
        assert msg.name == "bot"

    def test_content_isinstance_str_check(self) -> None:
        """Code that checks isinstance(msg.content, str) still works."""
        msg = ChatMessage(role="user", content="hello")
        assert isinstance(msg.content, str)

    def test_content_isinstance_list_check(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[TextBlock(text="hi")],
        )
        assert isinstance(msg.content, list)


# ---------------------------------------------------------------------------
# OpenAI serialization
# ---------------------------------------------------------------------------


class TestOpenAISerialization:
    def test_str_content_unchanged(self) -> None:
        msg = ChatMessage(role="user", content="hello")
        result = OpenAIProvider._serialize_message(msg)
        assert result == {"role": "user", "content": "hello"}

    def test_text_block_serialization(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[TextBlock(text="describe this")],
        )
        result = OpenAIProvider._serialize_message(msg)
        assert result["content"] == [{"type": "text", "text": "describe this"}]

    def test_image_url_serialization(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[
                TextBlock(text="what is this?"),
                ImageBlock(url="https://example.com/img.png", detail="high"),
            ],
        )
        result = OpenAIProvider._serialize_message(msg)
        assert len(result["content"]) == 2
        assert result["content"][0] == {"type": "text", "text": "what is this?"}
        assert result["content"][1] == {
            "type": "image_url",
            "image_url": {"url": "https://example.com/img.png", "detail": "high"},
        }

    def test_image_base64_serialization(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[
                ImageBlock(
                    base64_data="aGVsbG8=",
                    media_type="image/jpeg",
                    detail="low",
                ),
            ],
        )
        result = OpenAIProvider._serialize_message(msg)
        img_part = result["content"][0]
        assert img_part["type"] == "image_url"
        assert img_part["image_url"]["url"] == "data:image/jpeg;base64,aGVsbG8="
        assert img_part["image_url"]["detail"] == "low"

    def test_audio_serialization_fallback(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[AudioBlock(url="https://example.com/audio.wav")],
        )
        result = OpenAIProvider._serialize_message(msg)
        assert result["content"] == [
            {"type": "text", "text": "[Audio: https://example.com/audio.wav]"}
        ]

    def test_audio_embedded_label(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[AudioBlock(base64_data="QUFB")],
        )
        result = OpenAIProvider._serialize_message(msg)
        assert result["content"] == [{"type": "text", "text": "[Audio: embedded]"}]

    def test_tool_calls_preserved_with_multimodal(self) -> None:
        """tool_calls on an assistant message survive multimodal serialization."""
        from agent33.llm.base import ToolCall, ToolCallFunction

        msg = ChatMessage(
            role="assistant",
            content=[TextBlock(text="calling tool")],
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function=ToolCallFunction(name="fn", arguments="{}"),
                )
            ],
        )
        result = OpenAIProvider._serialize_message(msg)
        assert "tool_calls" in result
        assert result["tool_calls"][0]["id"] == "call_1"


# ---------------------------------------------------------------------------
# Ollama serialization
# ---------------------------------------------------------------------------


class TestOllamaSerialization:
    def test_str_content_unchanged(self) -> None:
        msg = ChatMessage(role="user", content="hello")
        result = OllamaProvider._serialize_message(msg)
        assert result["content"] == "hello"
        assert "images" not in result

    def test_text_block_serialization(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[TextBlock(text="describe this")],
        )
        result = OllamaProvider._serialize_message(msg)
        assert result["content"] == "describe this"
        assert "images" not in result

    def test_image_base64_serialization(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[
                TextBlock(text="what is this?"),
                ImageBlock(base64_data="aGVsbG8="),
            ],
        )
        result = OllamaProvider._serialize_message(msg)
        assert result["content"] == "what is this?"
        assert result["images"] == ["aGVsbG8="]

    def test_image_url_only_no_images_array(self) -> None:
        """Ollama only supports base64 images; URL-only images are skipped."""
        msg = ChatMessage(
            role="user",
            content=[
                TextBlock(text="hello"),
                ImageBlock(url="https://example.com/img.png"),
            ],
        )
        result = OllamaProvider._serialize_message(msg)
        assert result["content"] == "hello"
        assert "images" not in result

    def test_multiple_images(self) -> None:
        msg = ChatMessage(
            role="user",
            content=[
                TextBlock(text="compare"),
                ImageBlock(base64_data="img1"),
                ImageBlock(base64_data="img2"),
            ],
        )
        result = OllamaProvider._serialize_message(msg)
        assert result["content"] == "compare"
        assert result["images"] == ["img1", "img2"]

    def test_tool_calls_preserved_with_multimodal(self) -> None:
        from agent33.llm.base import ToolCall, ToolCallFunction

        msg = ChatMessage(
            role="assistant",
            content=[TextBlock(text="calling tool")],
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function=ToolCallFunction(name="fn", arguments="{}"),
                )
            ],
        )
        result = OllamaProvider._serialize_message(msg)
        assert "tool_calls" in result
        assert result["content"] == "calling tool"


# ---------------------------------------------------------------------------
# MockLLM integration
# ---------------------------------------------------------------------------


class TestMockLLMWithMultimodal:
    @pytest.mark.asyncio
    async def test_multimodal_message_matching(self) -> None:
        from agent33.testing.mock_llm import MockLLMProvider

        provider = MockLLMProvider({"describe this": "A cat"})
        messages = [
            ChatMessage(
                role="user",
                content=[
                    TextBlock(text="describe this"),
                    ImageBlock(url="https://example.com/cat.png"),
                ],
            )
        ]
        result = await provider.complete(messages, model="mock")
        assert result.content == "A cat"

    @pytest.mark.asyncio
    async def test_str_message_still_matches(self) -> None:
        from agent33.testing.mock_llm import MockLLMProvider

        provider = MockLLMProvider({"hello": "world"})
        messages = [ChatMessage(role="user", content="hello")]
        result = await provider.complete(messages, model="mock")
        assert result.content == "world"
