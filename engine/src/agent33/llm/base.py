"""Base LLM provider protocol and shared types."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class StreamingNotSupportedError(Exception):
    """Raised when streaming is requested for a provider that does not support it."""


@dataclasses.dataclass(frozen=True, slots=True)
class ToolCallFunction:
    """Function details within a tool call."""

    name: str
    arguments: str  # JSON string of arguments


@dataclasses.dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool call from an LLM response."""

    id: str
    function: ToolCallFunction


@dataclasses.dataclass(frozen=True, slots=True)
class LLMResponse:
    """Response from an LLM provider."""

    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    tool_calls: list[ToolCall] | None = None
    finish_reason: str = "stop"
    usage_available: bool = True

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def has_tool_calls(self) -> bool:
        """Return True if the response contains tool calls."""
        return self.tool_calls is not None and len(self.tool_calls) > 0


@dataclasses.dataclass(frozen=True, slots=True)
class ToolCallDelta:
    """Incremental tool-call fragment emitted during streaming."""

    index: int
    id: str = ""
    name: str = ""
    arguments_fragment: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class LLMStreamChunk:
    """A single chunk from an LLM streaming response."""

    delta_content: str = ""
    delta_tool_calls: list[ToolCall] = dataclasses.field(default_factory=list)
    tool_call_delta: ToolCallDelta | None = None
    finish_reason: str | None = None
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usage_available: bool = False


# ---------------------------------------------------------------------------
# Multimodal content blocks
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class TextBlock:
    """Text content block."""

    text: str


@dataclasses.dataclass(frozen=True, slots=True)
class ImageBlock:
    """Image content block."""

    url: str | None = None
    base64_data: str | None = None
    media_type: str = "image/png"
    detail: str = "auto"


@dataclasses.dataclass(frozen=True, slots=True)
class AudioBlock:
    """Audio content block."""

    url: str | None = None
    base64_data: str | None = None
    media_type: str = "audio/wav"


ContentPart = TextBlock | ImageBlock | AudioBlock


@dataclasses.dataclass(frozen=True, slots=True)
class ChatMessage:
    """A single message in a conversation."""

    role: str
    content: str | list[ContentPart]
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str = ""
    name: str = ""

    @property
    def text_content(self) -> str:
        """Extract text content, regardless of whether content is str or list."""
        if isinstance(self.content, str):
            return self.content
        return " ".join(block.text for block in self.content if isinstance(block, TextBlock))


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that all LLM providers must implement."""

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Generate a completion from the given messages."""
        ...

    async def list_models(self) -> list[str]:
        """Return available model identifiers."""
        ...

    async def stream_complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        """Stream completion chunks. Default raises StreamingNotSupportedError."""
        raise StreamingNotSupportedError("Streaming not supported by this provider")
        # Make it an async generator
        if False:  # pragma: no cover
            yield LLMStreamChunk()
