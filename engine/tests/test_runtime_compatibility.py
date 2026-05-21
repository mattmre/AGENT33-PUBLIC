"""Focused compatibility tests for the supported chat runtime contracts."""

from __future__ import annotations

from typing import Any

import pytest

from agent33.llm.base import ChatMessage, LLMResponse
from agent33.llm.ollama import OllamaProvider
from agent33.llm.openai import OpenAIProvider


def _messages() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="You are a test agent."),
        ChatMessage(role="user", content='{"query":"hello"}'),
    ]


def _tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "shell",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        }
    ]


@pytest.mark.asyncio
async def test_openai_complete_payload_matches_supported_contract() -> None:
    provider = OpenAIProvider(api_key="test-key", base_url="http://example.com/v1")
    captured: dict[str, Any] = {}

    async def _fake_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured["path"] = path
        captured["payload"] = payload
        return {
            "model": "gpt-4o",
            "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 2},
        }

    provider._post = _fake_post  # type: ignore[method-assign]
    result = await provider.complete(_messages(), model="gpt-4o", max_tokens=128, tools=_tools())

    assert captured["path"] == "/chat/completions"
    assert captured["payload"] == {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": '{"query":"hello"}'},
        ],
        "temperature": 0.7,
        "max_tokens": 128,
        "tools": [
            {
                "type": "function",
                "function": _tools()[0],
            }
        ],
    }
    assert isinstance(result, LLMResponse)
    assert result.model == "gpt-4o"
    await provider.close()


@pytest.mark.asyncio
async def test_openai_complete_parses_tool_calls_from_supported_contract() -> None:
    provider = OpenAIProvider(api_key="test-key", base_url="http://example.com/v1")

    async def _fake_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "shell",
                                    "arguments": '{"command":"pwd"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 11, "completion_tokens": 3},
        }

    provider._post = _fake_post  # type: ignore[method-assign]
    result = await provider.complete(_messages(), model="gpt-4o", tools=_tools())

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls is not None
    assert result.tool_calls[0].function.name == "shell"
    assert result.tool_calls[0].function.arguments == '{"command":"pwd"}'
    await provider.close()


@pytest.mark.asyncio
async def test_openai_stream_payload_matches_supported_contract() -> None:
    provider = OpenAIProvider(api_key="test-key", base_url="http://example.com/v1")
    captured: dict[str, Any] = {}

    async def _fake_stream_lines(path: str, payload: dict[str, Any]):  # type: ignore[no-untyped-def]
        captured["path"] = path
        captured["payload"] = payload
        yield "data: [DONE]"

    provider._stream_lines = _fake_stream_lines  # type: ignore[method-assign]
    _ = [
        chunk
        async for chunk in provider.stream_complete(_messages(), model="gpt-4o", tools=_tools())
    ]

    assert captured["path"] == "/chat/completions"
    assert captured["payload"] == {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": '{"query":"hello"}'},
        ],
        "temperature": 0.7,
        "stream": True,
        "tools": [
            {
                "type": "function",
                "function": _tools()[0],
            }
        ],
    }
    await provider.close()


@pytest.mark.asyncio
async def test_ollama_complete_payload_matches_supported_contract() -> None:
    provider = OllamaProvider(base_url="http://localhost:11434")
    captured: dict[str, Any] = {}

    async def _fake_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
        captured["path"] = path
        captured["payload"] = payload
        return {
            "model": "llama3.2",
            "message": {"content": "ok"},
            "prompt_eval_count": 9,
            "eval_count": 4,
        }

    provider._post = _fake_post  # type: ignore[method-assign]
    result = await provider.complete(
        _messages(),
        model="llama3.2",
        max_tokens=64,
        tools=_tools(),
    )

    assert captured["path"] == "/api/chat"
    assert captured["payload"] == {
        "model": "llama3.2",
        "messages": [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": '{"query":"hello"}'},
        ],
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 64,
        },
        "tools": [
            {
                "type": "function",
                "function": _tools()[0],
            }
        ],
    }
    assert result.model == "llama3.2"
    await provider.close()


@pytest.mark.asyncio
async def test_ollama_complete_parses_tool_calls_from_supported_contract() -> None:
    provider = OllamaProvider(base_url="http://localhost:11434")

    async def _fake_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:  # noqa: ARG001
        return {
            "model": "llama3.2",
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "shell",
                            "arguments": {"command": "pwd"},
                        },
                    }
                ],
            },
            "prompt_eval_count": 9,
            "eval_count": 4,
        }

    provider._post = _fake_post  # type: ignore[method-assign]
    result = await provider.complete(_messages(), model="llama3.2", tools=_tools())

    assert result.finish_reason == "tool_calls"
    assert result.tool_calls is not None
    assert result.tool_calls[0].function.arguments == '{"command": "pwd"}'
    await provider.close()


@pytest.mark.asyncio
async def test_ollama_stream_payload_matches_supported_contract() -> None:
    provider = OllamaProvider(base_url="http://localhost:11434")
    captured: dict[str, Any] = {}

    async def _fake_stream_lines(path: str, payload: dict[str, Any]):  # type: ignore[no-untyped-def]
        captured["path"] = path
        captured["payload"] = payload
        yield '{"message":{"content":"ok"},"done":true}'

    provider._stream_lines = _fake_stream_lines  # type: ignore[method-assign]
    _ = [
        chunk
        async for chunk in provider.stream_complete(_messages(), model="llama3.2", tools=_tools())
    ]

    assert captured["path"] == "/api/chat"
    assert captured["payload"] == {
        "model": "llama3.2",
        "messages": [
            {"role": "system", "content": "You are a test agent."},
            {"role": "user", "content": '{"query":"hello"}'},
        ],
        "stream": True,
        "options": {"temperature": 0.7},
        "tools": [
            {
                "type": "function",
                "function": _tools()[0],
            }
        ],
    }
    await provider.close()
