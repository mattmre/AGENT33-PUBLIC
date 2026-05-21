"""Tests for delegation SSE progress relay.

Verifies that when a parent agent delegates to a child via DelegateSubtaskTool,
progress events from the child's tool loop are relayed through the parent's
event stream via the event_sink callback on ToolContext.

Tests cover:
  - delegation_started event is emitted when child agent is spawned
  - Child events are wrapped as delegation_progress events
  - delegation_completed event is emitted when child finishes
  - Backward compatibility: no event_sink -> original loop.run() path
  - Fail-open: event_sink errors do not break delegation execution
  - New event types exist in EventType
  - ToolContext supports event_sink field
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent33.agents.events import ToolLoopEvent
from agent33.llm.base import ChatMessage, LLMResponse, ToolCall, ToolCallFunction
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.builtin.delegate_subtask import DelegateSubtaskTool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_router() -> MagicMock:
    """Create a mock ModelRouter."""
    router = MagicMock()
    router.complete = AsyncMock()
    return router


@pytest.fixture()
def mock_tool_registry() -> MagicMock:
    """Create a mock ToolRegistry with no tools."""
    registry = MagicMock()
    registry.list_all.return_value = []
    return registry


@pytest.fixture()
def delegate_tool(mock_router: MagicMock, mock_tool_registry: MagicMock) -> DelegateSubtaskTool:
    return DelegateSubtaskTool(router=mock_router, tool_registry=mock_tool_registry)


@pytest.fixture()
def base_context() -> ToolContext:
    return ToolContext(
        tool_policies={"delegation_depth": "0"},
        tenant_id="test-tenant",
        session_id="test-session",
    )


def _make_stream_events(
    *,
    content: str = "Child finished",
    tool_calls_made: int = 0,
) -> list[ToolLoopEvent]:
    """Build a realistic sequence of ToolLoopEvents that run_stream would emit."""
    return [
        ToolLoopEvent(
            event_type="loop_started",
            iteration=0,
            data={"max_iterations": 20, "tools_count": 1},
        ),
        ToolLoopEvent(
            event_type="iteration_started",
            iteration=1,
            data={"message_count": 2},
        ),
        ToolLoopEvent(
            event_type="llm_request",
            iteration=1,
            data={"model": "llama3.2", "temperature": 0.7, "tools_count": 1},
        ),
        ToolLoopEvent(
            event_type="llm_response",
            iteration=1,
            data={
                "has_tool_calls": False,
                "content_length": len(content),
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "usage_available": True,
                "finish_reason": "stop",
            },
        ),
        ToolLoopEvent(
            event_type="completed",
            iteration=1,
            data={
                "termination_reason": "completed",
                "total_tokens": 30,
                "tokens_available": True,
                "tool_calls_made": tool_calls_made,
                "tools_used": [],
                "output": {"response": content},
            },
        ),
    ]


async def _fake_run_stream(
    events: list[ToolLoopEvent],
    messages: list[ChatMessage],
    model: str,
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> Any:
    """Async generator that yields pre-built events."""
    for event in events:
        yield event


# ---------------------------------------------------------------------------
# Event type registration test
# ---------------------------------------------------------------------------


class TestEventTypesRegistered:
    """Verify new delegation event types exist in EventType."""

    def test_delegation_started_is_valid_event_type(self) -> None:
        """delegation_started should be a valid EventType value."""
        event = ToolLoopEvent(
            event_type="delegation_started",
            iteration=0,
            data={"goal": "test", "delegation_id": "abc123"},
        )
        assert event.event_type == "delegation_started"

    def test_delegation_progress_is_valid_event_type(self) -> None:
        event = ToolLoopEvent(
            event_type="delegation_progress",
            iteration=1,
            data={"delegation_id": "abc123", "child_event_type": "llm_response"},
        )
        assert event.event_type == "delegation_progress"

    def test_delegation_completed_is_valid_event_type(self) -> None:
        event = ToolLoopEvent(
            event_type="delegation_completed",
            iteration=0,
            data={"delegation_id": "abc123", "status": "success"},
        )
        assert event.event_type == "delegation_completed"

    def test_delegation_events_serialize_to_sse(self) -> None:
        """All new event types should serialize via to_sse() without error."""
        for etype in ("delegation_started", "delegation_progress", "delegation_completed"):
            event = ToolLoopEvent(event_type=etype, iteration=0, data={"test": True})
            sse = event.to_sse()
            assert "data:" in sse
            payload = json.loads(sse.replace("data: ", "").strip())
            assert payload["event_type"] == etype


# ---------------------------------------------------------------------------
# ToolContext event_sink field test
# ---------------------------------------------------------------------------


class TestToolContextEventSink:
    """Verify ToolContext supports the event_sink field."""

    def test_tool_context_default_event_sink_is_none(self) -> None:
        ctx = ToolContext()
        assert ctx.event_sink is None

    def test_tool_context_with_event_sink(self) -> None:
        async def my_sink(event: Any) -> None:
            pass

        ctx = ToolContext(event_sink=my_sink)
        assert ctx.event_sink is my_sink

    def test_tool_context_replace_preserves_event_sink(self) -> None:
        async def my_sink(event: Any) -> None:
            pass

        ctx = ToolContext(event_sink=my_sink, tenant_id="t1")
        replaced = dataclasses.replace(ctx, session_id="s1")
        assert replaced.event_sink is my_sink
        assert replaced.tenant_id == "t1"
        assert replaced.session_id == "s1"

    def test_tool_context_replace_can_set_event_sink(self) -> None:
        ctx = ToolContext()
        assert ctx.event_sink is None

        async def my_sink(event: Any) -> None:
            pass

        replaced = dataclasses.replace(ctx, event_sink=my_sink)
        assert replaced.event_sink is my_sink


# ---------------------------------------------------------------------------
# Delegation SSE relay tests
# ---------------------------------------------------------------------------


class TestDelegationEmitsStartedEvent:
    """Verify delegation_started is emitted when child agent is spawned."""

    async def test_delegation_emits_started_event(
        self,
        delegate_tool: DelegateSubtaskTool,
    ) -> None:
        """When event_sink is set, delegation_started should be the first
        delegation event emitted, containing the goal and a delegation_id."""
        received_events: list[ToolLoopEvent] = []

        async def capture_event(event: ToolLoopEvent) -> None:
            received_events.append(event)

        context_with_sink = ToolContext(
            tool_policies={"delegation_depth": "0"},
            tenant_id="test-tenant",
            session_id="test-session",
            event_sink=capture_event,
        )

        stream_events = _make_stream_events(content="Done with task")

        async def fake_stream(*args: Any, **kwargs: Any) -> Any:
            for e in stream_events:
                yield e

        with patch("agent33.agents.tool_loop.ToolLoop") as mock_loop_cls:
            instance = mock_loop_cls.return_value
            instance.run_stream = fake_stream
            result = await delegate_tool.execute(
                {"goal": "Research something", "toolsets": ["shell"]},
                context_with_sink,
            )

        assert result.success

        # Find delegation_started events
        started_events = [e for e in received_events if e.event_type == "delegation_started"]
        assert len(started_events) == 1
        started = started_events[0]
        assert started.data["goal"] == "Research something"
        assert "delegation_id" in started.data
        assert len(started.data["delegation_id"]) == 12  # uuid hex[:12]


class TestDelegationRelaysChildEvents:
    """Verify child events are wrapped as delegation_progress events."""

    async def test_delegation_relays_child_events(
        self,
        delegate_tool: DelegateSubtaskTool,
    ) -> None:
        """Each child event should be wrapped as delegation_progress with
        the child_event_type and child_event data."""
        received_events: list[ToolLoopEvent] = []

        async def capture_event(event: ToolLoopEvent) -> None:
            received_events.append(event)

        context_with_sink = ToolContext(
            tool_policies={"delegation_depth": "0"},
            event_sink=capture_event,
        )

        stream_events = _make_stream_events(content="Analysis complete")

        async def fake_stream(*args: Any, **kwargs: Any) -> Any:
            for e in stream_events:
                yield e

        with patch("agent33.agents.tool_loop.ToolLoop") as mock_loop_cls:
            instance = mock_loop_cls.return_value
            instance.run_stream = fake_stream
            await delegate_tool.execute(
                {"goal": "Analyze data", "toolsets": ["shell"]},
                context_with_sink,
            )

        progress_events = [e for e in received_events if e.event_type == "delegation_progress"]

        # Should have one progress event per child event
        assert len(progress_events) == len(stream_events)

        # All progress events should share the same delegation_id
        delegation_ids = {e.data["delegation_id"] for e in progress_events}
        assert len(delegation_ids) == 1

        # Each progress event wraps the original child event type
        child_types = [e.data["child_event_type"] for e in progress_events]
        expected_types = [e.event_type for e in stream_events]
        assert child_types == expected_types

        # Each progress event carries the original child event data
        for progress, original in zip(progress_events, stream_events, strict=True):
            assert progress.data["child_event"] == original.data


class TestDelegationEmitsCompletedEvent:
    """Verify delegation_completed is emitted when child finishes."""

    async def test_delegation_emits_completed_event(
        self,
        delegate_tool: DelegateSubtaskTool,
    ) -> None:
        received_events: list[ToolLoopEvent] = []

        async def capture_event(event: ToolLoopEvent) -> None:
            received_events.append(event)

        context_with_sink = ToolContext(
            tool_policies={"delegation_depth": "0"},
            event_sink=capture_event,
        )

        stream_events = _make_stream_events(content="Task done")

        async def fake_stream(*args: Any, **kwargs: Any) -> Any:
            for e in stream_events:
                yield e

        with patch("agent33.agents.tool_loop.ToolLoop") as mock_loop_cls:
            instance = mock_loop_cls.return_value
            instance.run_stream = fake_stream
            result = await delegate_tool.execute(
                {"goal": "Finish task", "toolsets": ["shell"]},
                context_with_sink,
            )

        assert result.success

        completed_events = [e for e in received_events if e.event_type == "delegation_completed"]
        assert len(completed_events) == 1
        completed = completed_events[0]
        assert completed.data["status"] == "completed"
        assert "delegation_id" in completed.data

    async def test_delegation_event_sequence_order(
        self,
        delegate_tool: DelegateSubtaskTool,
    ) -> None:
        """Events should come in order: started -> progress* -> completed."""
        received_events: list[ToolLoopEvent] = []

        async def capture_event(event: ToolLoopEvent) -> None:
            received_events.append(event)

        context_with_sink = ToolContext(
            tool_policies={"delegation_depth": "0"},
            event_sink=capture_event,
        )

        stream_events = _make_stream_events()

        async def fake_stream(*args: Any, **kwargs: Any) -> Any:
            for e in stream_events:
                yield e

        with patch("agent33.agents.tool_loop.ToolLoop") as mock_loop_cls:
            instance = mock_loop_cls.return_value
            instance.run_stream = fake_stream
            await delegate_tool.execute(
                {"goal": "Sequential test", "toolsets": ["shell"]},
                context_with_sink,
            )

        delegation_events = [
            e
            for e in received_events
            if e.event_type
            in ("delegation_started", "delegation_progress", "delegation_completed")
        ]

        # First event is delegation_started
        assert delegation_events[0].event_type == "delegation_started"
        # Last event is delegation_completed
        assert delegation_events[-1].event_type == "delegation_completed"
        # Everything in between is delegation_progress
        for e in delegation_events[1:-1]:
            assert e.event_type == "delegation_progress"


class TestDelegationWithoutEventSinkUsesRun:
    """Verify backward compatibility: no event_sink -> original loop.run() path."""

    async def test_delegation_without_event_sink_uses_run(
        self,
        delegate_tool: DelegateSubtaskTool,
    ) -> None:
        """When context has no event_sink, the tool should call loop.run()
        instead of loop.run_stream()."""
        context_no_sink = ToolContext(
            tool_policies={"delegation_depth": "0"},
        )
        assert context_no_sink.event_sink is None

        run_called = False
        run_stream_called = False

        class FakeToolLoop:
            def __init__(self, **kwargs: Any) -> None:
                pass

            async def run(self, **kwargs: Any) -> Any:
                nonlocal run_called
                run_called = True
                from types import SimpleNamespace

                return SimpleNamespace(
                    raw_response="Non-streaming result",
                    output={"result": "done"},
                )

            async def run_stream(self, **kwargs: Any) -> Any:
                nonlocal run_stream_called
                run_stream_called = True
                yield ToolLoopEvent(event_type="completed", iteration=0, data={})

        with patch("agent33.agents.tool_loop.ToolLoop", FakeToolLoop):
            result = await delegate_tool.execute(
                {"goal": "Test non-streaming", "toolsets": ["shell"]},
                context_no_sink,
            )

        assert result.success
        assert run_called, "loop.run() should have been called"
        assert not run_stream_called, "loop.run_stream() should NOT have been called"
        assert "Non-streaming result" in result.output


class TestDelegationEventSinkFailureIsFailOpen:
    """Event sink errors must never break delegation execution."""

    async def test_event_sink_failure_is_fail_open(
        self,
        delegate_tool: DelegateSubtaskTool,
    ) -> None:
        """If event_sink raises an exception, delegation should still
        complete successfully. Events are best-effort."""
        call_count = 0

        async def broken_sink(event: ToolLoopEvent) -> None:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Sink is broken!")

        context_with_broken_sink = ToolContext(
            tool_policies={"delegation_depth": "0"},
            event_sink=broken_sink,
        )

        stream_events = _make_stream_events(content="Result despite broken sink")

        async def fake_stream(*args: Any, **kwargs: Any) -> Any:
            for e in stream_events:
                yield e

        with patch("agent33.agents.tool_loop.ToolLoop") as mock_loop_cls:
            instance = mock_loop_cls.return_value
            instance.run_stream = fake_stream
            result = await delegate_tool.execute(
                {"goal": "Work despite broken sink", "toolsets": ["shell"]},
                context_with_broken_sink,
            )

        # Delegation should succeed despite sink errors
        assert result.success
        # The sink was called (delegation_started + progress events + delegation_completed)
        assert call_count > 0


class TestDelegationSingleShotNoStreaming:
    """When no tools are provided, the tool makes a single LLM call without streaming."""

    async def test_no_tools_uses_single_shot_even_with_event_sink(
        self,
        delegate_tool: DelegateSubtaskTool,
        mock_router: MagicMock,
    ) -> None:
        """Without toolsets, even if event_sink is set, the fallback
        single-shot LLM call path should be used (no ToolLoop)."""
        received_events: list[ToolLoopEvent] = []

        async def capture_event(event: ToolLoopEvent) -> None:
            received_events.append(event)

        context_with_sink = ToolContext(
            tool_policies={"delegation_depth": "0"},
            event_sink=capture_event,
        )

        mock_router.complete.return_value = LLMResponse(
            content="Direct LLM response",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
        )

        result = await delegate_tool.execute(
            {"goal": "Simple question, no tools needed"},
            context_with_sink,
        )

        assert result.success
        assert result.output == "Direct LLM response"
        # No delegation events since no ToolLoop was used
        assert len(received_events) == 0
        mock_router.complete.assert_called_once()


class TestToolLoopStreamDelegationRelay:
    """Integration test: verify ToolLoop.run_stream() relays delegation
    events from tools that use event_sink."""

    async def test_run_stream_yields_delegation_events_from_tool(self) -> None:
        """When a tool pushes events via event_sink during run_stream(),
        those events should be yielded by run_stream() alongside the
        normal tool loop events."""
        from agent33.agents.tool_loop import ToolLoop, ToolLoopConfig

        # Build a tool that pushes delegation events via context.event_sink
        class DelegatingTool:
            name = "test_delegator"
            description = "A tool that emits delegation events"

            async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
                if context.event_sink is not None:
                    await context.event_sink(
                        ToolLoopEvent(
                            event_type="delegation_started",
                            iteration=0,
                            data={"goal": "sub-task", "delegation_id": "test123"},
                        )
                    )
                    await context.event_sink(
                        ToolLoopEvent(
                            event_type="delegation_progress",
                            iteration=1,
                            data={
                                "delegation_id": "test123",
                                "child_event_type": "llm_response",
                                "child_event": {"content_length": 42},
                            },
                        )
                    )
                    await context.event_sink(
                        ToolLoopEvent(
                            event_type="delegation_completed",
                            iteration=0,
                            data={"delegation_id": "test123", "status": "success"},
                        )
                    )
                return ToolResult.ok("Delegation complete")

        # Build a mock tool registry
        tool = DelegatingTool()
        mock_registry = MagicMock()
        mock_registry.list_all.return_value = [tool]
        mock_registry.get_entry.return_value = None

        async def mock_validated_execute(
            name: str, params: dict[str, Any], context: ToolContext
        ) -> ToolResult:
            return await tool.execute(params, context)

        mock_registry.validated_execute = AsyncMock(side_effect=mock_validated_execute)

        # Build a mock router that returns a tool call, then a text response
        router = MagicMock()
        tool_call = ToolCall(
            id="call-1",
            function=ToolCallFunction(
                name="test_delegator",
                arguments="{}",
            ),
        )
        router.complete = AsyncMock(
            side_effect=[
                # First call: LLM requests tool call
                LLMResponse(
                    content="Let me delegate",
                    model="test",
                    prompt_tokens=10,
                    completion_tokens=5,
                    tool_calls=[tool_call],
                    finish_reason="tool_calls",
                ),
                # Second call: LLM returns text (completed)
                LLMResponse(
                    content="All done",
                    model="test",
                    prompt_tokens=15,
                    completion_tokens=10,
                ),
            ]
        )

        loop = ToolLoop(
            router=router,
            tool_registry=mock_registry,
            tool_context=ToolContext(),
            config=ToolLoopConfig(enable_double_confirmation=False),
        )

        events: list[ToolLoopEvent] = []
        async for event in loop.run_stream(
            messages=[
                ChatMessage(role="system", content="You are a helper"),
                ChatMessage(role="user", content="Do something"),
            ],
            model="test",
        ):
            events.append(event)

        event_types = [e.event_type for e in events]

        # Normal loop events should be present
        assert "loop_started" in event_types
        assert "completed" in event_types

        # Delegation events should be relayed
        assert "delegation_started" in event_types
        assert "delegation_progress" in event_types
        assert "delegation_completed" in event_types

        # Verify delegation events have correct data
        deleg_started = [e for e in events if e.event_type == "delegation_started"]
        assert len(deleg_started) == 1
        assert deleg_started[0].data["delegation_id"] == "test123"

        deleg_progress = [e for e in events if e.event_type == "delegation_progress"]
        assert len(deleg_progress) == 1
        assert deleg_progress[0].data["child_event_type"] == "llm_response"

        deleg_completed = [e for e in events if e.event_type == "delegation_completed"]
        assert len(deleg_completed) == 1
        assert deleg_completed[0].data["status"] == "success"
