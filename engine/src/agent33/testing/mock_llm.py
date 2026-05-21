"""Mock LLM provider for deterministic testing."""

from __future__ import annotations

from typing import Any

from agent33.llm.base import ChatMessage, LLMResponse


class MockLLMProvider:
    """LLM provider that returns deterministic responses from a configured map.

    Implements the :class:`~agent33.llm.base.LLMProvider` protocol.

    Parameters
    ----------
    response_map:
        Dictionary mapping user message content strings to response
        content strings.  When the last user message matches a key the
        corresponding value is returned.  If no match is found the user
        message is echoed back.
    """

    def __init__(self, response_map: dict[str, str] | None = None) -> None:
        self._response_map: dict[str, str] = response_map or {}

    def set_response(self, input_content: str, output_content: str) -> None:
        """Add or update a single mapping."""
        self._response_map[input_content] = output_content

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Return a deterministic response based on the response map.

        Looks up the content of the last user message in the response map.
        Falls back to echoing the user content if no mapping exists.
        """
        user_content = ""
        for msg in reversed(messages):
            if msg.role == "user":
                user_content = msg.text_content
                break

        response_text = self._response_map.get(user_content, user_content)

        return LLMResponse(
            content=response_text,
            model=model,
            prompt_tokens=len(user_content),
            completion_tokens=len(response_text),
        )

    async def list_models(self) -> list[str]:
        """Return a single mock model identifier."""
        return ["mock-model"]
