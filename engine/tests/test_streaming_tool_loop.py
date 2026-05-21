"""Tests for Phase 38a: Streaming tool-loop events."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from agent33.agents.events import ToolLoopEvent
from agent33.llm.base import (
    ChatMessage,
    LLMResponse,
    LLMStreamChunk,
    ToolCall,
    ToolCallFunction,
)
from agent33.tools.base import ToolContext, ToolResult

# ---------------------------------------------------------------------------
# Helpers (following existing test_tool_loop.py patterns)
# ---------------------------------------------------------------------------


def _text_response(
    content: str = "final answer",
    model: str = "test-model",
    prompt_tokens: int = 10,
    completion_tokens: int = 10,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tool_calls=None,
        finish_reason="stop",
    )


def _tool_response(
    tool_calls: list[ToolCall],
    content: str = "",
    model: str = "test-model",
    prompt_tokens: int = 15,
    completion_tokens: int = 15,
) -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        tool_calls=tool_calls,
        finish_reason="tool_calls",
    )


def _make_tool_call(
    name: str = "shell",
    arguments: str = '{"command": "ls"}',
    call_id: str = "call_1",
) -> ToolCall:
    return ToolCall(id=call_id, function=ToolCallFunction(name=name, arguments=arguments))


def _make_mock_tool(name: str = "shell", description: str = "Run a command") -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.execute = AsyncMock(return_value=ToolResult.ok("output"))
    return tool


def _make_registry(*tools: MagicMock) -> MagicMock:
    registry = MagicMock()
    registry.list_all.return_value = list(tools)
    registry.get_entry.return_value = None

    async def _validated_execute(
        name: str, params: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        for t in tools:
            if t.name == name:
                return await t.execute(params, context)
        return ToolResult.fail(f"Tool '{name}' not found in registry")

    registry.validated_execute = AsyncMock(side_effect=_validated_execute)
    return registry


def _make_router(*responses: LLMResponse) -> MagicMock:
    router = MagicMock()
    router.complete = AsyncMock(side_effect=list(responses))
    return router


def _make_streaming_router(chunks: list[LLMStreamChunk]) -> MagicMock:
    async def _stream_complete(messages: Any, *, model: str = "", **kwargs: Any) -> Any:
        del messages, model, kwargs
        for chunk in chunks:
            yield chunk

    router = MagicMock()
    router.stream_complete = _stream_complete
    router.complete = AsyncMock(return_value=_text_response("fallback"))
    return router


def _initial_messages() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="You are a helpful agent."),
        ChatMessage(role="user", content="Do the task."),
    ]


# ---------------------------------------------------------------------------
# ToolLoopEvent tests
# ---------------------------------------------------------------------------


class TestToolLoopEvent:
    def test_event_creation(self) -> None:
        event = ToolLoopEvent(event_type="loop_started", iteration=0)
        assert event.event_type == "loop_started"
        assert event.iteration == 0
        assert event.timestamp > 0
        assert event.data == {}

    def test_event_with_data(self) -> None:
        event = ToolLoopEvent(
            event_type="llm_response",
            iteration=1,
            data={"tokens": 100},
        )
        assert event.data["tokens"] == 100

    def test_event_to_sse(self) -> None:
        event = ToolLoopEvent(
            event_type="completed",
            iteration=3,
            data={"reason": "natural"},
        )
        sse = event.to_sse()
        assert sse.startswith("data: ")
        assert sse.endswith("\n\n")
        payload = json.loads(sse[6:-2])
        assert payload["event_type"] == "completed"
        assert payload["iteration"] == 3
        assert payload["data"]["reason"] == "natural"
        assert "timestamp" in payload

    def test_event_frozen(self) -> None:
        event = ToolLoopEvent(event_type="error", iteration=1)
        try:
            event.iteration = 2  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# LLMStreamChunk tests
# ---------------------------------------------------------------------------


class TestLLMStreamChunk:
    def test_chunk_defaults(self) -> None:
        chunk = LLMStreamChunk()
        assert chunk.delta_content == ""
        assert chunk.delta_tool_calls == []
        assert chunk.finish_reason is None
        assert chunk.model == ""
        assert chunk.prompt_tokens == 0
        assert chunk.completion_tokens == 0
        assert chunk.usage_available is False

    def test_chunk_with_content(self) -> None:
        chunk = LLMStreamChunk(delta_content="Hello", model="gpt-4")
        assert chunk.delta_content == "Hello"
        assert chunk.model == "gpt-4"

    def test_chunk_with_finish_reason(self) -> None:
        chunk = LLMStreamChunk(finish_reason="stop", model="gpt-4")
        assert chunk.finish_reason == "stop"


# ---------------------------------------------------------------------------
# Streaming tool loop tests
# ---------------------------------------------------------------------------


class TestStreamingToolLoop:
    async def test_stream_simple_response(self) -> None:
        """Stream a simple response with no tool calls."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(_text_response("Hello, how can I help?"))
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        event_types = [e.event_type for e in events]
        assert "loop_started" in event_types
        assert "iteration_started" in event_types
        assert "llm_request" in event_types
        assert "llm_response" in event_types
        assert "completed" in event_types
        # completed should be last
        assert events[-1].event_type == "completed"
        assert events[-1].data["termination_reason"] == "completed"

    async def test_stream_with_tool_calls(self) -> None:
        """Stream with tool calls should emit tool events."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        tc = _make_tool_call(name="shell", arguments='{"command": "ls"}', call_id="call_1")
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response([tc]),
            _text_response("Done!"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        event_types = [e.event_type for e in events]
        assert "tool_call_requested" in event_types
        assert "tool_call_started" in event_types
        assert "tool_call_completed" in event_types
        assert events[-1].event_type == "completed"
        assert events[-1].data["termination_reason"] == "completed"

        # Check tool_call_requested data
        req_event = next(e for e in events if e.event_type == "tool_call_requested")
        assert req_event.data["tools"] == ["shell"]
        assert req_event.data["count"] == 1

        # Check tool_call_started data
        start_event = next(e for e in events if e.event_type == "tool_call_started")
        assert start_event.data["tool"] == "shell"
        assert start_event.data["call_id"] == "call_1"

        # Check tool_call_completed data
        comp_event = next(e for e in events if e.event_type == "tool_call_completed")
        assert comp_event.data["tool"] == "shell"
        assert comp_event.data["success"] is True

    async def test_stream_llm_error_retries_until_threshold(self) -> None:
        """Streaming should retry LLM errors until the configured threshold is reached."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = MagicMock()
        router.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        registry = _make_registry()
        config = ToolLoopConfig(
            max_iterations=5,
            error_threshold=2,
            enable_double_confirmation=False,
        )

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        error_events = [e for e in events if e.event_type == "error"]
        assert len(error_events) == 2
        assert events[-1].event_type == "completed"
        assert events[-1].data["termination_reason"] == "error"
        assert router.complete.await_count == 2

        # Verify error event data
        assert "LLM unavailable" in error_events[0].data["error"]
        assert error_events[0].data["phase"] == "llm_call"
        assert error_events[0].data["retrying"] is True
        assert error_events[1].data["retrying"] is False

    async def test_stream_llm_error_can_recover_on_retry(self) -> None:
        """A transient LLM error should not force streaming termination."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = MagicMock()
        router.complete = AsyncMock(
            side_effect=[RuntimeError("LLM unavailable"), _text_response("Recovered")]
        )
        registry = _make_registry()
        config = ToolLoopConfig(
            max_iterations=5,
            error_threshold=3,
            enable_double_confirmation=False,
        )

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        error_events = [e for e in events if e.event_type == "error"]
        assert len(error_events) == 1
        assert error_events[0].data["retrying"] is True
        assert events[-1].event_type == "completed"
        assert events[-1].data["termination_reason"] == "completed"
        assert router.complete.await_count == 2

    async def test_stream_max_iterations(self) -> None:
        """Reaching max iterations should complete with max_iterations reason."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        tc = _make_tool_call()
        tool = _make_mock_tool()
        # Always return tool calls so loop continues
        router = _make_router(*[_tool_response([tc], content="working") for _ in range(10)])
        registry = _make_registry(tool)
        config = ToolLoopConfig(max_iterations=2, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        assert events[-1].event_type == "completed"
        assert events[-1].data["termination_reason"] == "max_iterations"
        assert events[-1].data["output"] == {"response": "working"}

    async def test_stream_loop_started_data(self) -> None:
        """The loop_started event should include max_iterations and tools_count."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(_text_response("ok"))
        tool = _make_mock_tool()
        registry = _make_registry(tool)
        config = ToolLoopConfig(max_iterations=10, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        started = events[0]
        assert started.event_type == "loop_started"
        assert started.data["max_iterations"] == 10

    async def test_stream_llm_response_data(self) -> None:
        """The llm_response event should include token counts."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(_text_response("hello", prompt_tokens=42, completion_tokens=7))
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        llm_resp = next(e for e in events if e.event_type == "llm_response")
        assert llm_resp.data["prompt_tokens"] == 42
        assert llm_resp.data["completion_tokens"] == 7
        assert llm_resp.data["has_tool_calls"] is False

    async def test_stream_completed_includes_stats(self) -> None:
        """The completed event should include total_tokens and tool stats."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        tc = _make_tool_call()
        tool = _make_mock_tool()
        router = _make_router(_tool_response([tc]), _text_response("done"))
        registry = _make_registry(tool)
        config = ToolLoopConfig(enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        completed = events[-1]
        assert completed.data["total_tokens"] > 0
        assert completed.data["tool_calls_made"] == 1
        assert "shell" in completed.data["tools_used"]

    async def test_stream_budget_enforcement_blocks_after_tool_iteration(self) -> None:
        """End-of-iteration budget checks should terminate streaming with budget_exceeded."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig
        from agent33.autonomy.models import EnforcementResult

        tc = _make_tool_call()
        tool = _make_mock_tool()
        router = _make_router(_tool_response([tc]))
        registry = _make_registry(tool)
        enforcer = MagicMock()
        enforcer.record_iteration.return_value = EnforcementResult.BLOCKED
        enforcer.check_duration.return_value = EnforcementResult.ALLOWED

        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            runtime_enforcer=enforcer,
            config=ToolLoopConfig(enable_double_confirmation=False),
        )

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        blocked = next(e for e in events if e.event_type == "tool_call_blocked")
        assert blocked.data["reason"] == "budget_exceeded"
        assert blocked.data["phase"] == "iteration"
        assert events[-1].data["termination_reason"] == "budget_exceeded"

    async def test_stream_duration_budget_enforcement_blocks_after_tool_iteration(self) -> None:
        """Duration budget checks should also terminate streaming with budget_exceeded."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig
        from agent33.autonomy.models import EnforcementResult

        tc = _make_tool_call()
        tool = _make_mock_tool()
        router = _make_router(_tool_response([tc]))
        registry = _make_registry(tool)
        enforcer = MagicMock()
        enforcer.record_iteration.return_value = EnforcementResult.ALLOWED
        enforcer.check_duration.return_value = EnforcementResult.BLOCKED

        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            runtime_enforcer=enforcer,
            config=ToolLoopConfig(enable_double_confirmation=False),
        )

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        blocked = next(e for e in events if e.event_type == "tool_call_blocked")
        assert blocked.data["reason"] == "budget_exceeded"
        assert blocked.data["phase"] == "duration"
        assert events[-1].data["termination_reason"] == "budget_exceeded"

    async def test_stream_tool_iteration_resets_consecutive_errors(self) -> None:
        """A successful tool iteration should reset the LLM consecutive-error counter."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        tc = _make_tool_call("shell", '{"command": "ls"}', "call_good")
        tool = _make_mock_tool("shell")
        router = MagicMock()
        router.complete = AsyncMock(
            side_effect=[
                RuntimeError("first failure"),
                _tool_response([tc]),
                RuntimeError("second failure"),
                _text_response("Recovered after tool call"),
            ]
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(
            max_iterations=5,
            error_threshold=2,
            enable_double_confirmation=False,
        )

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        error_events = [e for e in events if e.event_type == "error"]
        assert len(error_events) == 2
        assert events[-1].data["termination_reason"] == "completed"
        assert router.complete.await_count == 4

    async def test_stream_falls_back_to_non_streaming_when_finish_reason_requires_tools(
        self,
    ) -> None:
        """Fallback when streaming ends with raw tool_calls but emits no deltas."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        tc = _make_tool_call(name="shell", arguments='{"command": "pwd"}', call_id="call_1")
        tool = _make_mock_tool("shell")
        streamed_chunk = LLMStreamChunk(finish_reason="tool_calls", model="test-model")

        async def _stream_complete(*args: Any, **kwargs: Any):  # noqa: ARG001
            yield streamed_chunk

        router = MagicMock()
        router.stream_complete = _stream_complete
        router.complete = AsyncMock(side_effect=[_tool_response([tc]), _text_response("Done!")])
        registry = _make_registry(tool)
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        event_types = [event.event_type for event in events]
        assert "tool_call_requested" in event_types
        assert events[-1].event_type == "completed"
        assert events[-1].data["termination_reason"] == "completed"
        assert router.complete.await_count == 2

    async def test_stream_preserves_chunk_usage_and_finish_reason(self) -> None:
        """Streaming should retain chunk token usage and finish reason."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        chunks = [
            LLMStreamChunk(delta_content="partial ", model="stream-model"),
            LLMStreamChunk(
                delta_content="answer",
                model="stream-model",
                prompt_tokens=11,
                completion_tokens=13,
                finish_reason="length",
                usage_available=True,
            ),
        ]
        router = _make_streaming_router(chunks)
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        llm_response = next(e for e in events if e.event_type == "llm_response")
        assert llm_response.data["prompt_tokens"] == 11
        assert llm_response.data["completion_tokens"] == 13
        assert llm_response.data["finish_reason"] == "length"
        assert events[-1].data["total_tokens"] == 24


# ---------------------------------------------------------------------------
# Handoff interceptor tests (Gap 2 parity)
# ---------------------------------------------------------------------------


class TestStreamHandoffInterceptor:
    """Verify run_stream() performs context wipe when a handoff tool succeeds."""

    def _handoff_tool_call(
        self,
        *,
        source: str = "researcher",
        target: str = "implementer",
        objective: str = "Build the widget",
    ) -> ToolCall:
        ledger_data = {
            "source_agent": source,
            "target_agent": target,
            "objective": objective,
            "synthesized_context": "Context goes here",
        }
        return ToolCall(
            id="call_handoff_1",
            function=ToolCallFunction(
                name="handoff",
                arguments=json.dumps({"ledger_data": ledger_data}),
            ),
        )

    async def test_handoff_emits_context_wipe_event(self) -> None:
        """A successful handoff tool call should yield a handoff_context_wipe event."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        tc = self._handoff_tool_call(objective="Build the widget")
        handoff_tool = _make_mock_tool("handoff")
        router = _make_router(
            _tool_response([tc]),
            _text_response("Done after handoff"),
        )
        registry = _make_registry(handoff_tool)
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        event_types = [e.event_type for e in events]
        assert "handoff_context_wipe" in event_types

        wipe_event = next(e for e in events if e.event_type == "handoff_context_wipe")
        assert wipe_event.data["source"] == "researcher"
        assert wipe_event.data["target"] == "implementer"
        assert wipe_event.data["objective"] == "Build the widget"

    async def test_handoff_wipes_accumulated_messages(self) -> None:
        """After a handoff, accumulated_messages should contain only system + ledger."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        tc = self._handoff_tool_call()
        handoff_tool = _make_mock_tool("handoff")

        # Track the messages passed to the second LLM call (post-wipe)
        captured_messages: list[Any] = []
        call_count = 0

        async def _complete(messages: Any, **kwargs: Any) -> LLMResponse:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _tool_response([tc])
            captured_messages.extend(messages)
            return _text_response("Done after handoff")

        router = MagicMock()
        router.complete = AsyncMock(side_effect=_complete)
        registry = _make_registry(handoff_tool)
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        # Post-wipe messages should be: system prompt + user (ledger serialized)
        assert len(captured_messages) == 2
        assert captured_messages[0].role == "system"
        assert captured_messages[1].role == "user"
        assert "Build the widget" in captured_messages[1].content

    async def test_handoff_records_observation(self) -> None:
        """Handoff interceptor should call _record_observation with handoff_context_wipe."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        tc = self._handoff_tool_call(objective="Deploy service")
        handoff_tool = _make_mock_tool("handoff")
        router = _make_router(
            _tool_response([tc]),
            _text_response("Done"),
        )
        registry = _make_registry(handoff_tool)
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        obs_capture = AsyncMock()
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=config,
            observation_capture=obs_capture,
            session_id="sess-1",
            agent_name="test-agent",
        )

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        # Find the handoff observation call
        handoff_obs_calls = [
            c
            for c in obs_capture.record.call_args_list
            if c.args[0].event_type == "handoff_context_wipe"
        ]
        assert len(handoff_obs_calls) == 1
        obs = handoff_obs_calls[0].args[0]
        assert "Deploy service" in obs.content
        assert obs.metadata["source"] == "researcher"

    async def test_handoff_failure_does_not_crash_loop(self) -> None:
        """If handoff parsing fails, the loop should log an error and continue."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        # Malformed ledger_data (missing required fields)
        bad_tc = ToolCall(
            id="call_bad",
            function=ToolCallFunction(
                name="handoff",
                arguments=json.dumps({"ledger_data": {"bad": "data"}}),
            ),
        )
        handoff_tool = _make_mock_tool("handoff")
        router = _make_router(
            _tool_response([bad_tc]),
            _text_response("Recovered"),
        )
        registry = _make_registry(handoff_tool)
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        # Should complete without handoff_context_wipe (it failed silently)
        event_types = [e.event_type for e in events]
        assert "handoff_context_wipe" not in event_types
        assert events[-1].event_type == "completed"
        assert events[-1].data["termination_reason"] == "completed"


# ---------------------------------------------------------------------------
# Double-confirmation tests (Gap 3 parity)
# ---------------------------------------------------------------------------


class TestStreamDoubleConfirmation:
    """Verify run_stream() double-confirmation flow matches run()."""

    async def test_no_confirmation_when_disabled(self) -> None:
        """With enable_double_confirmation=False, text responses break immediately."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(_text_response("Final answer"))
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        event_types = [e.event_type for e in events]
        assert "confirmation_prompt" not in event_types
        assert events[-1].data["termination_reason"] == "completed"

    async def test_confirmation_prompt_emitted_on_first_text_response(self) -> None:
        """With double-confirmation enabled, the first text response triggers a prompt."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(
            _text_response("I think I'm done"),
            _text_response("COMPLETED: The answer is 42"),
        )
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=True)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        event_types = [e.event_type for e in events]
        assert "confirmation_prompt" in event_types
        prompt_event = next(e for e in events if e.event_type == "confirmation_prompt")
        assert prompt_event.data["content"] == "I think I'm done"

    async def test_confirmed_completion_emits_result_event(self) -> None:
        """COMPLETED: prefix should be stripped and confirmation_result emitted."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(
            _text_response("I think I'm done"),
            _text_response("COMPLETED: The answer is 42"),
        )
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=True)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        result_events = [e for e in events if e.event_type == "confirmation_result"]
        assert len(result_events) == 1
        assert result_events[0].data["confirmed"] is True
        assert result_events[0].data["content"] == "The answer is 42"
        assert events[-1].data["termination_reason"] == "completed"

    async def test_continue_response_resets_confirmation_and_loops(self) -> None:
        """CONTINUE: response should reset confirmation_pending and keep looping."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(
            _text_response("I think I'm done"),
            _text_response("CONTINUE: need to check one more thing"),
            _text_response("Now truly done"),
            _text_response("COMPLETED: verified answer"),
        )
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=10, enable_double_confirmation=True)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        confirmation_prompts = [e for e in events if e.event_type == "confirmation_prompt"]
        confirmation_results = [e for e in events if e.event_type == "confirmation_result"]

        # Should have 2 prompts (first text, third text) and 2 results (CONTINUE, COMPLETED)
        assert len(confirmation_prompts) == 2
        assert len(confirmation_results) == 2
        assert confirmation_results[0].data["confirmed"] is False
        assert confirmation_results[1].data["confirmed"] is True
        assert events[-1].data["termination_reason"] == "completed"

    async def test_ambiguous_response_resends_prompt(self) -> None:
        """Ambiguous confirmation response should re-send the prompt."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(
            _text_response("I think I'm done"),
            _text_response("Maybe? I'm not sure"),  # ambiguous
            _text_response("COMPLETED: Yes, the answer is 42"),
        )
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=10, enable_double_confirmation=True)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        prompts = [e for e in events if e.event_type == "confirmation_prompt"]
        # First text triggers prompt, ambiguous re-triggers prompt
        assert len(prompts) == 2
        assert events[-1].data["termination_reason"] == "completed"

    async def test_confirmed_output_has_stripped_prefix(self) -> None:
        """The final output should have the COMPLETED: prefix stripped."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(
            _text_response("Almost done"),
            _text_response("COMPLETED: Final result here"),
        )
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=True)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        completed = events[-1]
        assert completed.event_type == "completed"
        # The output should reflect the stripped content from final_response
        assert "Final result here" in str(completed.data["output"])

    async def test_tool_calls_reset_confirmation_pending(self) -> None:
        """Tool calls in the middle should reset confirmation_pending flag."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        tc = _make_tool_call()
        tool = _make_mock_tool()
        router = _make_router(
            _text_response("I think I'm done"),  # triggers confirmation
            _text_response("CONTINUE: need tools"),  # CONTINUE resets
            _tool_response([tc]),  # tool call resets confirmation_pending
            _text_response("Now truly done"),  # fresh confirmation cycle
            _text_response("COMPLETED: Final answer"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(max_iterations=10, enable_double_confirmation=True)

        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        # Should complete without errors
        assert events[-1].event_type == "completed"
        assert events[-1].data["termination_reason"] == "completed"
        # Tool call should have happened
        assert events[-1].data["tool_calls_made"] == 1


# ---------------------------------------------------------------------------
# Observation recording tests (Gap 1 parity)
# ---------------------------------------------------------------------------


class TestStreamObservationRecording:
    """Verify run_stream() records LLM response observations like run()."""

    async def test_llm_response_observation_recorded(self) -> None:
        """Each LLM response should trigger an observation record."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(_text_response("Hello world", model="obs-model"))
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        obs_capture = AsyncMock()
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=config,
            observation_capture=obs_capture,
            session_id="sess-obs",
            agent_name="obs-agent",
        )

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        # Find llm_response observations
        llm_obs = [
            c for c in obs_capture.record.call_args_list if c.args[0].event_type == "llm_response"
        ]
        assert len(llm_obs) >= 1
        obs = llm_obs[0].args[0]
        assert obs.session_id == "sess-obs"
        assert obs.agent_name == "obs-agent"
        assert obs.content == "Hello world"
        assert obs.metadata["model"] == "obs-model"
        assert obs.metadata["iteration"] == 1

    async def test_observation_metadata_includes_token_info(self) -> None:
        """Observation metadata should include token counts when available."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        router = _make_router(_text_response("Answer", prompt_tokens=50, completion_tokens=25))
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        obs_capture = AsyncMock()
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=config,
            observation_capture=obs_capture,
            session_id="sess-2",
            agent_name="agent-2",
        )

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        llm_obs = [
            c for c in obs_capture.record.call_args_list if c.args[0].event_type == "llm_response"
        ]
        assert len(llm_obs) >= 1
        meta = llm_obs[0].args[0].metadata
        assert meta["tokens"] == 75  # total_tokens = 50 + 25
        assert meta["usage_available"] is True
        assert meta["has_tool_calls"] is False

    async def test_observation_content_truncated_at_2000_chars(self) -> None:
        """LLM response observation content should be truncated to 2000 chars."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        long_content = "x" * 5000
        router = _make_router(_text_response(long_content))
        registry = _make_registry()
        config = ToolLoopConfig(max_iterations=5, enable_double_confirmation=False)

        obs_capture = AsyncMock()
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            config=config,
            observation_capture=obs_capture,
            session_id="sess-3",
            agent_name="agent-3",
        )

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(_initial_messages(), model="test-model"):
            events.append(event)

        llm_obs = [
            c for c in obs_capture.record.call_args_list if c.args[0].event_type == "llm_response"
        ]
        assert len(llm_obs) >= 1
        assert len(llm_obs[0].args[0].content) == 2000


# ---------------------------------------------------------------------------
# Provider method existence tests
# ---------------------------------------------------------------------------


class TestProviderStreaming:
    def test_openai_has_stream_complete(self) -> None:
        from agent33.llm.openai import OpenAIProvider

        assert hasattr(OpenAIProvider, "stream_complete")

    def test_ollama_has_stream_complete(self) -> None:
        from agent33.llm.ollama import OllamaProvider

        assert hasattr(OllamaProvider, "stream_complete")

    def test_router_has_stream_complete(self) -> None:
        from agent33.llm.router import ModelRouter

        assert hasattr(ModelRouter, "stream_complete")
