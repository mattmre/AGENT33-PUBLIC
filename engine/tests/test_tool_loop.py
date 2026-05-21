"""Tests for the iterative tool-use loop (Layer 2).

Covers termination conditions, tool execution, double-confirmation,
token tracking, observation recording, budget enforcement, error handling,
and edge cases.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.agents.tool_loop import (
    CONFIRMATION_PROMPT,
    ToolLoop,
    ToolLoopConfig,
    ToolLoopResult,
    ToolLoopState,
)
from agent33.discovery.service import ToolDiscoveryMatch
from agent33.llm.base import ChatMessage, LLMResponse, ToolCall, ToolCallFunction
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.discovery_runtime import (
    DISCOVER_TOOLS_TOOL_NAME,
    DiscoverToolsTool,
    SessionToolRegistryView,
    ToolActivationManager,
)
from agent33.tools.registry import ToolRegistry
from agent33.tools.registry_entry import ToolRegistryEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text_response(
    content: str = "final answer",
    model: str = "test-model",
    prompt_tokens: int = 10,
    completion_tokens: int = 10,
) -> LLMResponse:
    """Create a text-only LLM response (no tool calls)."""
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
    """Create an LLM response containing tool calls."""
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
    """Create a mock Tool with the correct protocol attributes."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.execute = AsyncMock(return_value=ToolResult.ok("output"))
    return tool


def _make_registry(*tools: MagicMock) -> MagicMock:
    """Create a mock ToolRegistry with the given tools."""
    registry = MagicMock()
    registry.list_all.return_value = list(tools)
    registry.get_entry.return_value = None

    async def _validated_execute(name: str, params: dict, context: ToolContext) -> ToolResult:
        for t in tools:
            if t.name == name:
                return await t.execute(params, context)
        return ToolResult.fail(f"Tool '{name}' not found in registry")

    registry.validated_execute = AsyncMock(side_effect=_validated_execute)
    return registry


def _make_router(*responses: LLMResponse) -> MagicMock:
    """Create a mock ModelRouter that returns responses in sequence."""
    router = MagicMock()
    router.complete = AsyncMock(side_effect=list(responses))
    return router


class _StaticTool:
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description or f"{name} description"
        self.execute = AsyncMock(return_value=ToolResult.ok(f"{name} output"))


def _register_runtime_tool(registry: ToolRegistry, tool: object) -> None:
    registry.register_with_entry(
        tool,
        ToolRegistryEntry(
            tool_id=tool.name,
            name=tool.name,
            version="1.0.0",
            description=getattr(tool, "description", ""),
            parameters_schema=getattr(tool, "parameters_schema", {}),
        ),
    )


def _initial_messages() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="You are a helpful agent."),
        ChatMessage(role="user", content="Do the task."),
    ]


# ---------------------------------------------------------------------------
# Termination tests
# ---------------------------------------------------------------------------


class TestTermination:
    async def test_text_response_completes_immediately_no_double_confirm(self) -> None:
        """Without double-confirmation, a text response exits on the first reply."""
        router = _make_router(_text_response("done"))
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        assert result.raw_response == "done"
        assert result.iterations == 1
        assert result.tool_calls_made == 0

    async def test_max_iterations_reached(self) -> None:
        """Loop stops after max_iterations even if LLM keeps requesting tools."""
        tc = _make_tool_call()
        tool = _make_mock_tool()
        router = _make_router(*[_tool_response([tc]) for _ in range(25)])
        registry = _make_registry(tool)
        config = ToolLoopConfig(max_iterations=3, enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "max_iterations"
        assert result.iterations == 3

    async def test_consecutive_errors_terminate_loop(self) -> None:
        """Loop terminates when consecutive errors reach the threshold."""
        router = MagicMock()
        router.complete = AsyncMock(side_effect=RuntimeError("LLM down"))
        registry = _make_registry()
        config = ToolLoopConfig(error_threshold=2, enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "error"
        assert result.iterations >= 2

    async def test_text_response_with_json_output(self) -> None:
        """Text response containing valid JSON is parsed into the output dict."""
        router = _make_router(_text_response('{"answer": 42}'))
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.output == {"answer": 42}
        assert result.termination_reason == "completed"


# ---------------------------------------------------------------------------
# Tool execution tests
# ---------------------------------------------------------------------------


class TestToolExecution:
    async def test_single_tool_call(self) -> None:
        """A single tool call is executed, result appended, then text completes."""
        tc = _make_tool_call("shell", '{"command": "ls"}')
        tool = _make_mock_tool("shell")
        tool.execute = AsyncMock(return_value=ToolResult.ok("file.txt"))
        router = _make_router(
            _tool_response([tc]),
            _text_response("done"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        assert result.tool_calls_made == 1
        assert "shell" in result.tools_used
        # validated_execute was called with the right args
        registry.validated_execute.assert_called_once()
        call_args = registry.validated_execute.call_args
        assert call_args[0][0] == "shell"
        assert call_args[0][1] == {"command": "ls"}

    async def test_multiple_tool_calls_in_one_response(self) -> None:
        """Multiple tool calls in a single LLM response are all executed."""
        tc1 = _make_tool_call("shell", '{"command": "ls"}', "call_1")
        tc2 = _make_tool_call("file_ops", '{"path": "/tmp/x"}', "call_2")
        shell = _make_mock_tool("shell")
        file_ops = _make_mock_tool("file_ops", "File operations")
        router = _make_router(
            _tool_response([tc1, tc2]),
            _text_response("all done"),
        )
        registry = _make_registry(shell, file_ops)
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.tool_calls_made == 2
        assert set(result.tools_used) == {"shell", "file_ops"}

    async def test_tool_not_found(self) -> None:
        """When a tool is not in the registry, an error result is returned to the LLM."""
        tc = _make_tool_call("nonexistent", '{"x": 1}')
        router = _make_router(
            _tool_response([tc]),
            _text_response("ok"),
        )
        registry = _make_registry()  # no tools
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        # The loop should still complete -- the error is passed back to the LLM
        assert result.termination_reason == "completed"
        # The second router call should have a tool message with an error
        second_call_messages = router.complete.call_args_list[1][0][0]
        tool_msg = [m for m in second_call_messages if m.role == "tool"][0]
        assert "Error:" in tool_msg.content or "not found" in tool_msg.content

    async def test_governance_blocks_tool(self) -> None:
        """When governance denies a tool, an error ToolResult is returned to the LLM."""
        tc = _make_tool_call("shell", '{"command": "rm -rf /"}')
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response([tc]),
            _text_response("ok"),
        )
        registry = _make_registry(tool)
        governance = MagicMock()
        governance.pre_execute_check.return_value = False
        governance.log_execution = MagicMock()
        context = ToolContext(user_scopes=["tools:execute"])
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            tool_governance=governance,
            tool_context=context,
            config=config,
        )

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        # The tool should NOT have been executed
        tool.execute.assert_not_called()
        # Governance check was called
        governance.pre_execute_check.assert_called_once()

    async def test_max_tool_calls_per_iteration_cap(self) -> None:
        """Only max_tool_calls_per_iteration calls are processed per response."""
        calls = [_make_tool_call("shell", '{"command": "echo"}', f"call_{i}") for i in range(10)]
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response(calls),
            _text_response("done"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(
            max_tool_calls_per_iteration=3,
            enable_double_confirmation=False,
        )
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.tool_calls_made == 3

    async def test_tool_result_appended_to_messages(self) -> None:
        """After tool execution, the assistant + tool messages are in the conversation."""
        tc = _make_tool_call("shell", '{"command": "pwd"}', "call_abc")
        tool = _make_mock_tool("shell")
        tool.execute = AsyncMock(return_value=ToolResult.ok("/home/user"))
        router = _make_router(
            _tool_response([tc], content="Let me check"),
            _text_response("done"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        await loop.run(_initial_messages(), model="m")

        # Inspect messages sent to the second LLM call
        second_call_messages = router.complete.call_args_list[1][0][0]
        assistant_msgs = [m for m in second_call_messages if m.role == "assistant"]
        tool_msgs = [m for m in second_call_messages if m.role == "tool"]

        assert len(assistant_msgs) == 1
        assert assistant_msgs[0].tool_calls is not None
        assert len(tool_msgs) == 1
        assert tool_msgs[0].content == "/home/user"
        assert tool_msgs[0].tool_call_id == "call_abc"
        assert tool_msgs[0].name == "shell"

    async def test_dynamic_visibility_refreshes_after_discovery_activation(self) -> None:
        """Dynamic tool visibility refreshes between iterations after discover_tools runs."""
        registry = ToolRegistry()
        discovery_service = MagicMock()
        discovery_service.discover_tools.return_value = [
            ToolDiscoveryMatch(name="shell", description="Run commands", score=9.0)
        ]
        activation_manager = ToolActivationManager()
        discover_tool = DiscoverToolsTool(
            discovery_service=discovery_service,
            activation_manager=activation_manager,
            mode="dynamic",
        )
        shell_tool = _StaticTool("shell", "Run commands")
        _register_runtime_tool(registry, discover_tool)
        _register_runtime_tool(registry, shell_tool)

        visible_registry = SessionToolRegistryView(
            registry,
            mode="dynamic",
            activation_manager=activation_manager,
            context=ToolContext(tenant_id="tenant-1", session_id="session-1"),
        )
        router = _make_router(
            _tool_response(
                [
                    _make_tool_call(
                        DISCOVER_TOOLS_TOOL_NAME,
                        '{"query": "run commands", "activation_limit": 1}',
                    )
                ]
            ),
            _text_response("done"),
        )
        loop = ToolLoop(
            router=router,
            tool_registry=visible_registry,
            tool_context=ToolContext(tenant_id="tenant-1", session_id="session-1"),
            config=ToolLoopConfig(enable_double_confirmation=False),
        )

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        first_tools = router.complete.call_args_list[0].kwargs["tools"]
        second_tools = router.complete.call_args_list[1].kwargs["tools"]
        assert [tool["name"] for tool in first_tools] == [DISCOVER_TOOLS_TOOL_NAME]
        assert [tool["name"] for tool in second_tools] == [
            DISCOVER_TOOLS_TOOL_NAME,
            "shell",
        ]


# ---------------------------------------------------------------------------
# Double-confirmation tests
# ---------------------------------------------------------------------------


class TestDoubleConfirmation:
    async def test_first_text_triggers_confirmation(self) -> None:
        """First text-only response sends the confirmation prompt."""
        router = _make_router(
            _text_response("I think I'm done"),
            _text_response("COMPLETED: Yes, confirmed done"),
        )
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=True)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        assert result.raw_response == "COMPLETED: Yes, confirmed done"
        assert result.iterations == 2

        # Verify confirmation prompt was injected
        second_call_messages = router.complete.call_args_list[1][0][0]
        user_msgs = [m for m in second_call_messages if m.role == "user"]
        assert any(CONFIRMATION_PROMPT in m.content for m in user_msgs)

    async def test_confirmed_second_text_exits(self) -> None:
        """After confirmation prompt, a second text response exits the loop."""
        router = _make_router(
            _text_response("answer is 42"),
            _text_response('COMPLETED: {"result": 42}'),
        )
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=True)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        assert result.output == {"result": 42}

    async def test_tool_calls_after_first_text_reset_confirmation(self) -> None:
        """If the LLM returns tools after a text response, confirmation resets."""
        tc = _make_tool_call("shell", '{"command": "verify"}')
        tool = _make_mock_tool("shell")
        router = _make_router(
            _text_response("maybe done"),  # triggers confirmation_pending
            _tool_response([tc]),  # resets confirmation_pending
            _text_response("now really done"),  # triggers confirmation again
            _text_response("COMPLETED: confirmed"),  # final confirmation
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(enable_double_confirmation=True)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        assert result.raw_response == "COMPLETED: confirmed"
        assert result.iterations == 4

    async def test_double_confirmation_disabled(self) -> None:
        """With double-confirmation off, first text exits immediately."""
        router = _make_router(_text_response("answer"))
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        assert result.iterations == 1
        # Only one LLM call -- no confirmation round-trip
        assert router.complete.call_count == 1


# ---------------------------------------------------------------------------
# Token tracking tests
# ---------------------------------------------------------------------------


class TestTokenTracking:
    async def test_tokens_accumulated_across_iterations(self) -> None:
        """Total tokens includes all iterations."""
        tc = _make_tool_call()
        tool = _make_mock_tool()
        router = _make_router(
            _tool_response([tc], prompt_tokens=100, completion_tokens=50),
            _text_response(prompt_tokens=80, completion_tokens=30),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.tokens_used == (100 + 50) + (80 + 30)

    async def test_tokens_tracked_on_error_termination(self) -> None:
        """Tokens from successful calls before errors are still counted."""
        router = MagicMock()
        router.complete = AsyncMock(
            side_effect=[
                _text_response(prompt_tokens=20, completion_tokens=10),
                RuntimeError("fail"),
                RuntimeError("fail again"),
            ]
        )
        registry = _make_registry()
        config = ToolLoopConfig(
            error_threshold=2,
            enable_double_confirmation=True,
        )
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.tokens_used == 30
        assert result.termination_reason == "error"


# ---------------------------------------------------------------------------
# Observation recording tests
# ---------------------------------------------------------------------------


class TestObservationRecording:
    async def test_llm_response_observation_recorded(self) -> None:
        """An observation is recorded for each LLM response."""
        router = _make_router(_text_response("done"))
        registry = _make_registry()
        obs_capture = MagicMock()
        obs_capture.record = AsyncMock(return_value="obs-1")
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            observation_capture=obs_capture,
            config=config,
            agent_name="test-agent",
            session_id="sess-1",
        )

        await loop.run(_initial_messages(), model="m")

        obs_capture.record.assert_called()
        obs_arg = obs_capture.record.call_args[0][0]
        assert obs_arg.event_type == "llm_response"
        assert obs_arg.agent_name == "test-agent"
        assert obs_arg.session_id == "sess-1"

    async def test_tool_call_observation_recorded(self) -> None:
        """An observation is recorded for each tool call."""
        tc = _make_tool_call("shell", '{"command": "ls"}')
        tool = _make_mock_tool("shell")
        tool.execute = AsyncMock(return_value=ToolResult.ok("file.txt"))
        router = _make_router(
            _tool_response([tc]),
            _text_response("done"),
        )
        registry = _make_registry(tool)
        obs_capture = MagicMock()
        obs_capture.record = AsyncMock(return_value="obs-2")
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            observation_capture=obs_capture,
            config=config,
        )

        await loop.run(_initial_messages(), model="m")

        # Should have at least 2 observations: 1 for LLM response + 1 for tool call
        assert obs_capture.record.call_count >= 2
        # Find the tool_call observation
        tool_obs = [
            call[0][0]
            for call in obs_capture.record.call_args_list
            if call[0][0].event_type == "tool_call"
        ]
        assert len(tool_obs) >= 1
        assert tool_obs[0].metadata["tool"] == "shell"
        assert tool_obs[0].metadata["success"] is True

    async def test_observation_failure_does_not_crash_loop(self) -> None:
        """If observation recording fails, the loop continues normally."""
        router = _make_router(_text_response("done"))
        registry = _make_registry()
        obs_capture = MagicMock()
        obs_capture.record = AsyncMock(side_effect=RuntimeError("storage down"))
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            observation_capture=obs_capture,
            config=config,
        )

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"


# ---------------------------------------------------------------------------
# Budget enforcement tests
# ---------------------------------------------------------------------------


class TestBudgetEnforcement:
    async def test_enforcer_blocks_iteration(self) -> None:
        """When RuntimeEnforcer blocks an iteration, the loop stops."""
        from agent33.autonomy.models import EnforcementResult

        tc = _make_tool_call()
        tool = _make_mock_tool()
        router = _make_router(
            _tool_response([tc]),
            _tool_response([tc]),  # second iteration -- blocked before LLM call returns
        )
        registry = _make_registry(tool)

        enforcer = MagicMock()
        enforcer.record_iteration.return_value = EnforcementResult.BLOCKED
        enforcer.check_duration.return_value = EnforcementResult.ALLOWED
        enforcer.check_command.return_value = EnforcementResult.ALLOWED

        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            runtime_enforcer=enforcer,
            config=config,
        )

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "budget_exceeded"

    async def test_enforcer_blocks_duration(self) -> None:
        """When duration check is blocked, loop terminates with budget_exceeded."""
        from agent33.autonomy.models import EnforcementResult

        tc = _make_tool_call()
        tool = _make_mock_tool()
        router = _make_router(
            _tool_response([tc]),
        )
        registry = _make_registry(tool)

        enforcer = MagicMock()
        enforcer.record_iteration.return_value = EnforcementResult.ALLOWED
        enforcer.check_duration.return_value = EnforcementResult.BLOCKED
        enforcer.check_command.return_value = EnforcementResult.ALLOWED

        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            runtime_enforcer=enforcer,
            config=config,
        )

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "budget_exceeded"

    async def test_enforcer_blocks_specific_tool(self) -> None:
        """When the enforcer blocks a specific tool via check_command, the loop stops."""
        from agent33.autonomy.models import EnforcementResult

        tc = _make_tool_call("dangerous_tool", '{"x": 1}')
        tool = _make_mock_tool("dangerous_tool")
        router = _make_router(_tool_response([tc]))
        registry = _make_registry(tool)

        enforcer = MagicMock()
        enforcer.check_command.return_value = EnforcementResult.BLOCKED
        enforcer.record_iteration.return_value = EnforcementResult.ALLOWED
        enforcer.check_duration.return_value = EnforcementResult.ALLOWED

        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            runtime_enforcer=enforcer,
            config=config,
        )

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "budget_exceeded"
        # The tool should not have been executed via validated_execute
        registry.validated_execute.assert_not_called()


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    async def test_malformed_tool_call_arguments(self) -> None:
        """Malformed JSON in tool call arguments creates an error result."""
        tc = _make_tool_call("shell", "not valid json!!!")
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response([tc]),
            _text_response("ok"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        # The tool should not have been executed (args were invalid)
        tool.execute.assert_not_called()
        # Error message was sent back to the LLM
        second_call_messages = router.complete.call_args_list[1][0][0]
        tool_msgs = [m for m in second_call_messages if m.role == "tool"]
        assert len(tool_msgs) == 1
        assert "Invalid JSON" in tool_msgs[0].content or "Error:" in tool_msgs[0].content

    async def test_tool_execution_exception(self) -> None:
        """When tool.execute raises, the error is caught and returned to the LLM."""
        tc = _make_tool_call("shell", '{"command": "crash"}')
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response([tc]),
            _text_response("recovered"),
        )
        registry = MagicMock()
        registry.list_all.return_value = [tool]
        registry.get_entry.return_value = None
        registry.validated_execute = AsyncMock(side_effect=RuntimeError("boom"))
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        # Error message in tool result
        second_call_messages = router.complete.call_args_list[1][0][0]
        tool_msgs = [m for m in second_call_messages if m.role == "tool"]
        assert any("boom" in m.content for m in tool_msgs)

    async def test_llm_error_mid_loop(self) -> None:
        """An LLM error after a successful iteration increments consecutive_errors."""
        tc = _make_tool_call()
        tool = _make_mock_tool()
        responses = [
            _tool_response([tc]),
        ]
        errors = [RuntimeError("e1"), RuntimeError("e2"), RuntimeError("e3")]

        call_count = 0

        async def _complete(*args, **kwargs):
            nonlocal call_count
            idx = call_count
            call_count += 1
            if idx == 0:
                return responses[0]
            raise errors[idx - 1]

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(side_effect=_complete)

        registry = _make_registry(tool)
        config = ToolLoopConfig(error_threshold=3, enable_double_confirmation=False)
        loop = ToolLoop(router=mock_router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "error"
        assert result.tool_calls_made == 1

    async def test_consecutive_errors_reset_on_tool_call(self) -> None:
        """Successful tool calls reset the consecutive error counter."""
        tc_bad = _make_tool_call("shell", "INVALID", "call_bad")
        tc_good = _make_tool_call("shell", '{"command": "ls"}', "call_good")
        tool = _make_mock_tool("shell")

        router = _make_router(
            _tool_response([tc_bad]),  # bad args -> 1 consecutive error
            _tool_response([tc_good]),  # good call -> resets to 0
            _text_response("done"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(error_threshold=3, enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    async def test_empty_tool_calls_list_treated_as_text(self) -> None:
        """An LLM response with an empty tool_calls list is treated as text."""
        response = LLMResponse(
            content="final answer",
            model="test-model",
            prompt_tokens=10,
            completion_tokens=10,
            tool_calls=[],  # empty list
            finish_reason="stop",
        )
        router = _make_router(response)
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        assert result.tool_calls_made == 0

    async def test_no_tools_available(self) -> None:
        """When no tools are registered, the loop still works (text only)."""
        router = _make_router(_text_response("no tools needed"))
        registry = _make_registry()  # no tools
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        assert result.tools_used == []

    async def test_parse_output_with_markdown_fences(self) -> None:
        """JSON wrapped in markdown fences is extracted correctly."""
        fenced = '```json\n{"status": "ok"}\n```'
        router = _make_router(_text_response(fenced))
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.output == {"status": "ok"}

    async def test_parse_output_plain_text_fallback(self) -> None:
        """Non-JSON text falls back to {"response": raw}."""
        router = _make_router(_text_response("just some text"))
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.output == {"response": "just some text"}

    async def test_model_passed_through(self) -> None:
        """The model name is passed to the router and reflected in the result."""
        router = _make_router(_text_response(model="gpt-4o"))
        registry = _make_registry()
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="gpt-4o")

        assert result.model == "gpt-4o"
        call_kwargs = router.complete.call_args[1]
        assert call_kwargs["model"] == "gpt-4o"

    async def test_tool_descriptions_passed_to_router(self) -> None:
        """Tool descriptions are collected and passed to router.complete()."""
        tool = _make_mock_tool("shell", "Run shell commands")
        router = _make_router(_text_response("done"))
        registry = _make_registry(tool)
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        await loop.run(_initial_messages(), model="m")

        call_kwargs = router.complete.call_args[1]
        tools_arg = call_kwargs.get("tools")
        assert tools_arg is not None
        assert len(tools_arg) == 1
        assert tools_arg[0]["name"] == "shell"
        assert tools_arg[0]["description"] == "Run shell commands"

    async def test_no_tools_sends_none_for_tools_param(self) -> None:
        """When no tools are registered, tools=None is sent to the router."""
        router = _make_router(_text_response("done"))
        registry = _make_registry()  # no tools
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        await loop.run(_initial_messages(), model="m")

        call_kwargs = router.complete.call_args[1]
        assert call_kwargs.get("tools") is None

    async def test_governance_audit_logged_on_success(self) -> None:
        """Governance log_execution is called after successful tool execution."""
        tc = _make_tool_call("shell", '{"command": "ls"}')
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response([tc]),
            _text_response("done"),
        )
        registry = _make_registry(tool)
        governance = MagicMock()
        governance.pre_execute_check.return_value = True
        governance.log_execution = MagicMock()
        context = ToolContext(user_scopes=["tools:execute"])
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(
            router=router,
            tool_registry=registry,
            tool_governance=governance,
            tool_context=context,
            config=config,
        )

        await loop.run(_initial_messages(), model="m")

        governance.log_execution.assert_called_once()
        log_args = governance.log_execution.call_args[0]
        assert log_args[0] == "shell"
        assert log_args[1] == {"command": "ls"}
        assert isinstance(log_args[2], ToolResult)

    async def test_tools_used_is_deduplicated(self) -> None:
        """tools_used list contains unique tool names, not duplicates."""
        tc = _make_tool_call("shell", '{"command": "a"}', "c1")
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response([tc]),
            _tool_response([_make_tool_call("shell", '{"command": "b"}', "c2")]),
            _text_response("done"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.tools_used == ["shell"]
        assert result.tool_calls_made == 2

    async def test_default_context_used_when_none_provided(self) -> None:
        """When no ToolContext is provided, a default is used for execution."""
        tc = _make_tool_call("shell", '{"command": "ls"}')
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response([tc]),
            _text_response("done"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(enable_double_confirmation=False)
        # Explicitly no tool_context
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        # validated_execute was called with a ToolContext
        context_arg = registry.validated_execute.call_args[0][2]
        assert isinstance(context_arg, ToolContext)


# ---------------------------------------------------------------------------
# Data class tests
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_tool_loop_config_defaults(self) -> None:
        config = ToolLoopConfig()
        assert config.max_iterations == 20
        assert config.max_tool_calls_per_iteration == 5
        assert config.error_threshold == 3
        assert config.enable_double_confirmation is True
        assert config.loop_detection_threshold == 0

    def test_tool_loop_state_initialization(self) -> None:
        state = ToolLoopState()
        assert state.iteration == 0
        assert state.total_tokens == 0
        assert state.tool_calls_made == 0
        assert state.tools_used == []
        assert state.consecutive_errors == 0
        assert state.confirmation_pending is False
        assert state.call_history == []


# ---------------------------------------------------------------------------
# Loop detection tests
# ---------------------------------------------------------------------------


class TestLoopDetection:
    async def test_identical_tool_calls_trigger_loop_detection(self) -> None:
        """Repeated identical tool calls trigger loop_detected termination."""
        tc = _make_tool_call("shell", '{"command": "ls"}', "call_1")
        tool = _make_mock_tool("shell")
        # LLM keeps making the same call
        router = _make_router(
            _tool_response([tc]),
            _tool_response([_make_tool_call("shell", '{"command": "ls"}', "call_2")]),
            _tool_response([_make_tool_call("shell", '{"command": "ls"}', "call_3")]),
            _text_response("done"),  # Should not reach this
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(loop_detection_threshold=3, enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "loop_detected"
        assert result.iterations == 3
        # Only 2 tool calls executed before detection
        assert result.tool_calls_made == 2

    async def test_non_identical_calls_do_not_trigger_loop(self) -> None:
        """Different tool calls or arguments do not trigger loop detection."""
        tc1 = _make_tool_call("shell", '{"command": "ls"}', "c1")
        tc2 = _make_tool_call("shell", '{"command": "pwd"}', "c2")
        tc3 = _make_tool_call("file_ops", '{"path": "/tmp"}', "c3")
        tool_shell = _make_mock_tool("shell")
        tool_file = _make_mock_tool("file_ops")
        router = _make_router(
            _tool_response([tc1]),
            _tool_response([tc2]),
            _tool_response([tc3]),
            _text_response("done"),
        )
        registry = _make_registry(tool_shell, tool_file)
        config = ToolLoopConfig(loop_detection_threshold=3, enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        assert result.termination_reason == "completed"
        assert result.tool_calls_made == 3

    async def test_loop_detection_disabled_when_threshold_zero(self) -> None:
        """Setting loop_detection_threshold to 0 disables loop detection."""
        tool = _make_mock_tool("shell")
        # Same call repeated 10 times
        router = _make_router(
            *[
                _tool_response([_make_tool_call("shell", '{"command": "ls"}', f"c{i}")])
                for i in range(10)
            ],
            _text_response("done"),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(
            loop_detection_threshold=0,
            max_iterations=15,
            enable_double_confirmation=False,
        )
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        # Should not trigger loop detection, completes normally
        assert result.termination_reason == "completed"
        assert result.tool_calls_made == 10

    async def test_loop_detection_with_sorted_arguments(self) -> None:
        """Arguments are sorted before comparison to detect loops with reordered keys."""
        # Same args but different JSON key order
        tc1 = _make_tool_call("shell", '{"command": "ls", "timeout": 30}', "c1")
        tc2 = _make_tool_call("shell", '{"timeout": 30, "command": "ls"}', "c2")
        tc3 = _make_tool_call("shell", '{"command": "ls", "timeout": 30}', "c3")
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response([tc1]),
            _tool_response([tc2]),
            _tool_response([tc3]),
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(loop_detection_threshold=3, enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        # Should detect the loop (same tool + same args despite ordering)
        assert result.termination_reason == "loop_detected"

    async def test_loop_resets_after_different_call(self) -> None:
        """Loop detection counter resets when a different call is made."""
        tc1 = _make_tool_call("shell", '{"command": "ls"}', "c1")
        tc2 = _make_tool_call("shell", '{"command": "ls"}', "c2")
        tc_different = _make_tool_call("shell", '{"command": "pwd"}', "c3")
        tc3 = _make_tool_call("shell", '{"command": "ls"}', "c4")
        tc4 = _make_tool_call("shell", '{"command": "ls"}', "c5")
        tc5 = _make_tool_call("shell", '{"command": "ls"}', "c6")
        tool = _make_mock_tool("shell")
        router = _make_router(
            _tool_response([tc1]),
            _tool_response([tc2]),
            _tool_response([tc_different]),  # Breaks the pattern
            _tool_response([tc3]),
            _tool_response([tc4]),
            _tool_response([tc5]),  # 3rd consecutive "ls" after the break
        )
        registry = _make_registry(tool)
        config = ToolLoopConfig(loop_detection_threshold=3, enable_double_confirmation=False)
        loop = ToolLoop(router=router, tool_registry=registry, config=config)

        result = await loop.run(_initial_messages(), model="m")

        # Should detect loop on iterations 4, 5, 6 (after the break at iteration 3)
        assert result.termination_reason == "loop_detected"
        assert result.tool_calls_made == 5  # Stops before executing the 6th

    def test_tool_loop_config_is_frozen(self) -> None:
        config = ToolLoopConfig()
        with pytest.raises(AttributeError):
            config.max_iterations = 10  # type: ignore[misc]

    def test_tool_loop_state_is_mutable(self) -> None:
        state = ToolLoopState()
        state.iteration = 5
        state.total_tokens = 100
        state.tool_calls_made = 3
        state.tools_used.append("shell")
        state.consecutive_errors = 1
        state.confirmation_pending = True
        assert state.iteration == 5
        assert state.tools_used == ["shell"]

    def test_tool_loop_result_is_frozen(self) -> None:
        result = ToolLoopResult(
            output={},
            raw_response="",
            tokens_used=0,
            model="m",
            iterations=1,
            tool_calls_made=0,
            tools_used=[],
            termination_reason="completed",
        )
        with pytest.raises(AttributeError):
            result.iterations = 5  # type: ignore[misc]
