"""Targeted tests for token-level streaming."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.agents.events import ToolLoopEvent
from agent33.llm import _stream_utils as stream_utils
from agent33.llm.base import (
    ChatMessage,
    LLMResponse,
    LLMStreamChunk,
    ToolCall,
    ToolCallDelta,
    ToolCallFunction,
)
from agent33.llm.ollama import OllamaProvider
from agent33.llm.openai import OpenAIProvider

if TYPE_CHECKING:
    from agent33.connectors.models import ConnectorRequest


class _StreamResponse:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    async def __aenter__(self) -> _StreamResponse:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):  # type: ignore[no-untyped-def]
        for line in self._lines:
            yield line


class _OpenAIStreamClient:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def stream(self, *args: Any, **kwargs: Any) -> _StreamResponse:
        return _StreamResponse(self._lines)

    async def aclose(self) -> None:
        return None


class _OllamaStreamClient:
    def __init__(self, *, lines: list[str]) -> None:
        self._lines = lines
        self.last_json: dict[str, Any] | None = None

    def stream(self, *args: Any, **kwargs: Any) -> _StreamResponse:
        self.last_json = kwargs.get("json")
        return _StreamResponse(self._lines)

    async def aclose(self) -> None:
        return None


class _BoundaryExecutor:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[ConnectorRequest] = []

    async def execute(self, request: ConnectorRequest, handler: Any) -> Any:
        self.calls.append(request)
        if self.failure is not None:
            raise self.failure
        return await handler(request)


def _make_registry(*tools: MagicMock) -> MagicMock:
    registry = MagicMock()
    registry.list_all.return_value = list(tools)
    registry.get_entry.return_value = None

    async def _validated_execute(name: str, params: dict[str, Any], context: Any) -> Any:
        for tool in tools:
            if tool.name == name:
                return await tool.execute(params, context)
        raise AssertionError(f"unknown tool: {name}")

    registry.validated_execute = AsyncMock(side_effect=_validated_execute)
    return registry


def _make_tool(name: str = "shell") -> MagicMock:
    from agent33.tools.base import ToolResult

    tool = MagicMock()
    tool.name = name
    tool.description = "mock tool"
    tool.execute = AsyncMock(return_value=ToolResult.ok("ok"))
    return tool


def _messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="hello")]


@pytest.mark.asyncio
async def test_openai_stream_complete_emits_tool_call_deltas() -> None:
    provider = OpenAIProvider(api_key="test-key", base_url="http://example.com/v1")
    provider._client = _OpenAIStreamClient(
        [
            'data: {"choices":[{"delta":{"content":"Hello "}}],"model":"gpt-4o"}',
            (
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1",'
                '"function":{"name":"shell","arguments":"{\\"command\\": "}}]}}],'
                '"model":"gpt-4o"}'
            ),
            (
                'data: {"choices":[{"delta":{"tool_calls":[{"index":0,'
                '"function":{"arguments":"\\"dir\\"}"}}]},"finish_reason":"tool_calls"}],'
                '"model":"gpt-4o"}'
            ),
            "data: [DONE]",
        ]
    )  # type: ignore[assignment]

    chunks = [chunk async for chunk in provider.stream_complete(_messages(), model="gpt-4o")]

    assert chunks[0].delta_content == "Hello "
    tool_deltas = [chunk.tool_call_delta for chunk in chunks if chunk.tool_call_delta is not None]
    assert len(tool_deltas) == 2
    assert tool_deltas[0].name == "shell"
    assert tool_deltas[1].arguments_fragment == '"dir"}'
    await provider.close()


@pytest.mark.asyncio
async def test_openai_stream_complete_uses_connector_boundary_executor() -> None:
    provider = OpenAIProvider(api_key="test-key", base_url="http://example.com/v1")
    provider._client = _OpenAIStreamClient(
        [
            'data: {"choices":[{"delta":{"content":"Hello"}}],"model":"gpt-4o"}',
            "data: [DONE]",
        ]
    )  # type: ignore[assignment]
    boundary = _BoundaryExecutor()
    provider._boundary_executor = boundary  # type: ignore[assignment]

    chunks = [chunk async for chunk in provider.stream_complete(_messages(), model="gpt-4o")]

    assert [chunk.delta_content for chunk in chunks] == ["Hello"]
    assert len(boundary.calls) == 1
    request = boundary.calls[0]
    assert request.connector == "llm:openai"
    assert request.operation == "POST /chat/completions"
    assert request.payload["stream"] is True
    await provider.close()


@pytest.mark.asyncio
async def test_openai_stream_complete_propagates_usage_chunk() -> None:
    provider = OpenAIProvider(api_key="test-key", base_url="http://example.com/v1")
    provider._client = _OpenAIStreamClient(
        [
            'data: {"choices":[{"delta":{"content":"Hello"}}],"model":"gpt-4o"}',
            (
                'data: {"choices":[],"usage":{"prompt_tokens":11,"completion_tokens":7},'
                '"model":"gpt-4o"}'
            ),
            "data: [DONE]",
        ]
    )  # type: ignore[assignment]

    chunks = [chunk async for chunk in provider.stream_complete(_messages(), model="gpt-4o")]

    usage_chunk = next(chunk for chunk in chunks if chunk.usage_available)
    assert usage_chunk.model == "gpt-4o"
    assert usage_chunk.prompt_tokens == 11
    assert usage_chunk.completion_tokens == 7
    await provider.close()


@pytest.mark.asyncio
async def test_ollama_stream_complete_sends_tools_and_emits_tool_delta() -> None:
    client = _OllamaStreamClient(
        lines=[
            json.dumps(
                {
                    "model": "llama3.2",
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "function": {
                                    "name": "shell",
                                    "arguments": {"command": "pwd"},
                                },
                            }
                        ]
                    },
                    "done": True,
                }
            )
        ]
    )
    provider = OllamaProvider(base_url="http://localhost:11434")
    provider._client = client  # type: ignore[assignment]

    chunks = [
        chunk
        async for chunk in provider.stream_complete(
            _messages(),
            model="llama3.2",
            tools=[{"name": "shell", "parameters": {"type": "object"}}],
        )
    ]

    assert client.last_json is not None
    assert "tools" in client.last_json
    tool_deltas = [chunk.tool_call_delta for chunk in chunks if chunk.tool_call_delta is not None]
    assert len(tool_deltas) == 1
    assert tool_deltas[0].name == "shell"
    assert tool_deltas[0].arguments_fragment == '{"command": "pwd"}'
    await provider.close()


@pytest.mark.asyncio
async def test_ollama_stream_complete_defaults_missing_tool_call_id_and_done_reason() -> None:
    client = _OllamaStreamClient(
        lines=[
            json.dumps(
                {
                    "model": "llama3.2",
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "shell",
                                    "arguments": {"command": "pwd"},
                                },
                            }
                        ]
                    },
                    "done": True,
                    "done_reason": "tool_calls",
                    "prompt_eval_count": 13,
                    "eval_count": 5,
                }
            )
        ]
    )
    provider = OllamaProvider(base_url="http://localhost:11434")
    provider._client = client  # type: ignore[assignment]

    chunks = [chunk async for chunk in provider.stream_complete(_messages(), model="llama3.2")]

    tool_delta = next(
        chunk.tool_call_delta for chunk in chunks if chunk.tool_call_delta is not None
    )
    assert tool_delta is not None
    assert tool_delta.id == "call_0"
    usage_chunk = next(chunk for chunk in chunks if chunk.usage_available)
    assert usage_chunk.finish_reason == "tool_calls"
    assert usage_chunk.model == "llama3.2"
    assert usage_chunk.prompt_tokens == 13
    assert usage_chunk.completion_tokens == 5
    await provider.close()


@pytest.mark.asyncio
async def test_ollama_stream_complete_propagates_boundary_blocking_error() -> None:
    provider = OllamaProvider(base_url="http://localhost:11434")
    provider._client = _OllamaStreamClient(lines=[])  # type: ignore[assignment]
    provider._boundary_executor = _BoundaryExecutor(failure=PermissionError("blocked by policy"))  # type: ignore[assignment]

    with pytest.raises(
        RuntimeError,
        match="Connector governance blocked llm:ollama/POST /api/chat",
    ):
        _ = [chunk async for chunk in provider.stream_complete(_messages(), model="llama3.2")]

    await provider.close()


@pytest.mark.asyncio
async def test_stream_lines_helpers_use_bounded_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_maxsizes: list[int] = []

    class RecordingQueue(asyncio.Queue[object]):
        def __init__(self, maxsize: int = 0) -> None:
            recorded_maxsizes.append(maxsize)
            super().__init__(maxsize=maxsize)

    monkeypatch.setattr(stream_utils.asyncio, "Queue", RecordingQueue)

    provider = OpenAIProvider(api_key="test-key", base_url="http://example.com/v1")
    provider._client = _OpenAIStreamClient(["data: [DONE]"])  # type: ignore[assignment]

    lines = [
        line
        async for line in provider._stream_lines(
            "/chat/completions",
            {"model": "gpt-4o", "stream": True},
        )
    ]

    assert lines == ["data: [DONE]"]
    assert recorded_maxsizes == [stream_utils._STREAM_LINE_QUEUE_MAXSIZE]
    assert recorded_maxsizes[0] > 0
    await provider.close()


@pytest.mark.asyncio
async def test_tool_loop_stream_uses_token_streaming_before_tool_execution() -> None:
    from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

    tool = _make_tool("shell")
    registry = _make_registry(tool)

    router = MagicMock()
    router.complete = AsyncMock(
        return_value=LLMResponse(
            content="",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=5,
            tool_calls=[
                ToolCall(
                    id="call_1",
                    function=ToolCallFunction(name="shell", arguments='{"command": "pwd"}'),
                )
            ],
            finish_reason="tool_calls",
        )
    )

    async def _stream_complete(*args: Any, **kwargs: Any):  # noqa: ARG001
        yield LLMStreamChunk(delta_content="Thinking ")
        yield LLMStreamChunk(
            tool_call_delta=ToolCallDelta(
                index=0,
                id="call_1",
                name="shell",
                arguments_fragment='{"command": "pwd"}',
            ),
            finish_reason="tool_calls",
            model="test-model",
        )

    router.stream_complete = _stream_complete

    loop = ToolLoop(
        router=router,
        tool_registry=registry,
        config=ToolLoopConfig(max_iterations=1, enable_double_confirmation=False),
    )

    events = [event async for event in loop.run_stream(_messages(), model="test-model")]

    assert any(event.event_type == "llm_token" for event in events)
    assert any(event.event_type == "tool_call_requested" for event in events)
    assert router.complete.await_count == 0


@pytest.mark.asyncio
async def test_tool_loop_stream_falls_back_to_complete_when_streaming_unsupported() -> None:
    from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

    router = MagicMock()
    router.complete = AsyncMock(
        return_value=LLMResponse(
            content="done",
            model="test-model",
            prompt_tokens=3,
            completion_tokens=2,
            tool_calls=None,
            finish_reason="stop",
        )
    )

    async def _unsupported_stream_complete(*args: Any, **kwargs: Any):  # noqa: ARG001
        raise NotImplementedError
        yield  # pragma: no cover

    router.stream_complete = _unsupported_stream_complete

    loop = ToolLoop(
        router=router,
        tool_registry=_make_registry(),
        config=ToolLoopConfig(max_iterations=1, enable_double_confirmation=False),
    )

    events = [event async for event in loop.run_stream(_messages(), model="test-model")]

    assert isinstance(events[-1], ToolLoopEvent)
    assert events[-1].event_type == "completed"
    assert events[-1].data["termination_reason"] == "completed"
    assert router.complete.await_count == 1


@pytest.mark.asyncio
async def test_tool_loop_stream_does_not_mask_real_type_error() -> None:
    from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

    router = MagicMock()
    router.complete = AsyncMock()

    async def _broken_stream_complete(*args: Any, **kwargs: Any):  # noqa: ARG001
        raise TypeError("stream parser bug")
        yield  # pragma: no cover

    router.stream_complete = _broken_stream_complete

    loop = ToolLoop(
        router=router,
        tool_registry=_make_registry(),
        config=ToolLoopConfig(max_iterations=1, enable_double_confirmation=False),
    )

    events = [event async for event in loop.run_stream(_messages(), model="test-model")]

    error_event = next(event for event in events if event.event_type == "error")
    assert error_event.data["phase"] == "llm_call"
    assert "stream parser bug" in error_event.data["error"]
    assert events[-1].data["termination_reason"] == "llm_error"
    assert router.complete.await_count == 0


@pytest.mark.asyncio
async def test_tool_loop_stream_explicitly_marks_usage_unavailable() -> None:
    from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

    router = MagicMock()
    router.complete = AsyncMock()

    async def _stream_complete(*args: Any, **kwargs: Any):  # noqa: ARG001
        yield LLMStreamChunk(delta_content="Hello ", model="stream-model")
        yield LLMStreamChunk(delta_content="world", finish_reason="stop", model="stream-model")

    router.stream_complete = _stream_complete

    loop = ToolLoop(
        router=router,
        tool_registry=_make_registry(),
        config=ToolLoopConfig(max_iterations=1, enable_double_confirmation=False),
    )

    events = [event async for event in loop.run_stream(_messages(), model="test-model")]

    response_event = next(event for event in events if event.event_type == "llm_response")
    assert response_event.data["usage_available"] is False
    assert response_event.data["prompt_tokens"] is None
    assert response_event.data["completion_tokens"] is None
    completed_event = events[-1]
    assert completed_event.data["tokens_available"] is False
    assert completed_event.data["total_tokens"] is None


@pytest.mark.asyncio
async def test_stream_response_events_preserve_streamed_model_finish_reason_and_usage() -> None:
    from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

    router = MagicMock()
    router.complete = AsyncMock()

    async def _stream_complete(*args: Any, **kwargs: Any):  # noqa: ARG001
        yield LLMStreamChunk(delta_content="Hello", model="stream-model")
        yield LLMStreamChunk(
            finish_reason="length",
            model="stream-model",
            prompt_tokens=9,
            completion_tokens=4,
            usage_available=True,
        )

    router.stream_complete = _stream_complete

    loop = ToolLoop(
        router=router,
        tool_registry=_make_registry(),
        config=ToolLoopConfig(max_iterations=1, enable_double_confirmation=False),
    )
    result_holder: dict[str, LLMResponse] = {}

    _ = [
        event
        async for event in loop._stream_response_events(  # noqa: SLF001
            _messages(),
            result_holder=result_holder,
            iteration=1,
            model="fallback-model",
            temperature=0.7,
            max_tokens=None,
            tools=None,
        )
    ]

    response = result_holder["response"]
    assert response.model == "stream-model"
    assert response.finish_reason == "length"
    assert response.usage_available is True
    assert response.prompt_tokens == 9
    assert response.completion_tokens == 4
