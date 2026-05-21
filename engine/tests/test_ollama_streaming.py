"""Tests for Ollama streaming metadata and tool-call normalization."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.llm.base import ChatMessage
from agent33.llm.ollama import OllamaProvider


class _MockStreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> _MockStreamResponse:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


@pytest.mark.asyncio
async def test_stream_complete_uses_call_prefix_for_missing_tool_ids() -> None:
    provider = OllamaProvider()
    provider._client = MagicMock()
    provider._client.aclose = AsyncMock()
    provider._client.stream.return_value = _MockStreamResponse(
        [
            json.dumps(
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "shell",
                                    "arguments": {"command": "dir"},
                                }
                            }
                        ]
                    },
                    "done": True,
                    "model": "llama3.2",
                    "prompt_eval_count": 7,
                    "eval_count": 5,
                }
            )
        ]
    )

    chunks = []
    async for chunk in provider.stream_complete(
        [ChatMessage(role="user", content="list files")],
        model="llama3.2",
    ):
        chunks.append(chunk)

    assert len(chunks) == 2
    tool_chunk = next(chunk for chunk in chunks if chunk.tool_call_delta is not None)
    assert tool_chunk.tool_call_delta.id == "call_0"
    assert tool_chunk.prompt_tokens == 7
    assert tool_chunk.completion_tokens == 5
