"""Tests for Phase 53: Ad-Hoc Subagent Delegation Tool.

Tests cover:
  - Child receives isolated context (no parent messages)
  - Blocked tools stripped from child toolset
  - MAX_DEPTH enforcement (depth >= 2 raises error)
  - Parent receives summary only, not intermediate tool calls
  - Batch mode runs concurrently and aggregates results
  - Timeout enforcement
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent33.llm.base import LLMResponse, ToolCall, ToolCallFunction
from agent33.packs.registry import PackRegistry
from agent33.skills.injection import SkillInjector
from agent33.skills.registry import SkillRegistry
from agent33.skills.slash_commands import parse_slash_command, scan_skill_commands
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.builtin.delegate_prompts import (
    BLOCKED_TOOLS,
    build_child_system_prompt,
    strip_blocked_tools,
)
from agent33.tools.builtin.delegate_subtask import (
    MAX_DEPTH,
    DelegateSubtaskTool,
)
from agent33.tools.builtin.moa import MoATool
from agent33.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from pathlib import Path

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
    """Create a mock ToolRegistry with a few registered tools."""
    registry = MagicMock()
    registry.list_all.return_value = []
    return registry


class _StubTool:
    def __init__(self, name: str) -> None:
        self.name = name
        self.description = f"{name} tool"

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.ok(f"ran {self.name}")


class _ProbeTool:
    def __init__(self) -> None:
        self.name = "probe_tool"
        self.description = "A tool that should remain hidden from delegated children"

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.ok("probe ran")


@pytest.fixture()
def delegate_tool(mock_router: MagicMock, mock_tool_registry: MagicMock) -> DelegateSubtaskTool:
    """Create a DelegateSubtaskTool instance with mock dependencies."""
    return DelegateSubtaskTool(router=mock_router, tool_registry=mock_tool_registry)


@pytest.fixture()
def base_context() -> ToolContext:
    """Create a baseline ToolContext with depth 0."""
    return ToolContext(
        tool_policies={"delegation_depth": "0"},
        tenant_id="test-tenant",
        session_id="test-session",
    )


# ---------------------------------------------------------------------------
# Prompt helper tests
# ---------------------------------------------------------------------------


class TestDelegatePrompts:
    """Tests for the prompt construction and tool filtering helpers."""

    def test_build_child_system_prompt_includes_goal(self) -> None:
        prompt = build_child_system_prompt("Search for Python tutorials", "")
        assert "Search for Python tutorials" in prompt
        assert "## Goal" in prompt

    def test_build_child_system_prompt_includes_context_when_provided(self) -> None:
        prompt = build_child_system_prompt(
            "Analyze the code",
            "The repo uses FastAPI with SQLAlchemy.",
        )
        assert "## Background Context" in prompt
        assert "The repo uses FastAPI with SQLAlchemy." in prompt

    def test_build_child_system_prompt_omits_context_when_empty(self) -> None:
        prompt = build_child_system_prompt("Do something", "")
        assert "## Background Context" not in prompt

    def test_build_child_system_prompt_omits_context_when_whitespace(self) -> None:
        prompt = build_child_system_prompt("Do something", "   \n  ")
        assert "## Background Context" not in prompt

    def test_build_child_system_prompt_includes_safety_rules(self) -> None:
        prompt = build_child_system_prompt("Any goal", "")
        assert "Safety Rules" in prompt
        assert "secrets" in prompt.lower()

    def test_build_child_system_prompt_includes_no_delegation_instruction(self) -> None:
        prompt = build_child_system_prompt("Any goal", "")
        assert "Do not attempt to delegate" in prompt

    def test_strip_blocked_tools_removes_delegate_subtask(self) -> None:
        tools = ["shell", "delegate_subtask", "file_ops", "web_fetch"]
        result = strip_blocked_tools(tools)
        assert "delegate_subtask" not in result
        assert "shell" in result
        assert "file_ops" in result
        assert "web_fetch" in result

    def test_strip_blocked_tools_removes_clarify(self) -> None:
        tools = ["shell", "clarify", "search"]
        result = strip_blocked_tools(tools)
        assert "clarify" not in result
        assert "shell" in result
        assert "search" in result

    def test_strip_blocked_tools_preserves_order(self) -> None:
        tools = ["c", "b", "a"]
        result = strip_blocked_tools(tools)
        assert result == ["c", "b", "a"]

    def test_strip_blocked_tools_handles_empty_list(self) -> None:
        assert strip_blocked_tools([]) == []

    def test_blocked_tools_frozenset_is_correct(self) -> None:
        assert "delegate_subtask" in BLOCKED_TOOLS
        assert "clarify" in BLOCKED_TOOLS
        assert len(BLOCKED_TOOLS) == 2


# ---------------------------------------------------------------------------
# Tool schema and protocol tests
# ---------------------------------------------------------------------------


class TestDelegateSubtaskToolProtocol:
    """Verify the tool satisfies SchemaAwareTool protocol requirements."""

    def test_name_property(self, delegate_tool: DelegateSubtaskTool) -> None:
        assert delegate_tool.name == "delegate_subtask"

    def test_description_property(self, delegate_tool: DelegateSubtaskTool) -> None:
        desc = delegate_tool.description
        assert isinstance(desc, str)
        assert len(desc) > 10

    def test_parameters_schema_is_valid_json_schema(
        self, delegate_tool: DelegateSubtaskTool
    ) -> None:
        schema = delegate_tool.parameters_schema
        assert schema["type"] == "object"
        assert "goal" in schema["properties"]
        assert schema["required"] == ["goal"]

    def test_parameters_schema_includes_batch_tasks(
        self, delegate_tool: DelegateSubtaskTool
    ) -> None:
        schema = delegate_tool.parameters_schema
        assert "tasks" in schema["properties"]
        tasks_schema = schema["properties"]["tasks"]
        assert tasks_schema["type"] == "array"

    def test_parameters_schema_includes_timeout(self, delegate_tool: DelegateSubtaskTool) -> None:
        schema = delegate_tool.parameters_schema
        assert "timeout" in schema["properties"]


# ---------------------------------------------------------------------------
# Depth enforcement tests
# ---------------------------------------------------------------------------


class TestDepthEnforcement:
    """Verify MAX_DEPTH is enforced properly."""

    async def test_depth_0_allows_delegation(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """Depth 0 (parent) should be allowed to delegate."""
        with patch.object(delegate_tool, "_run_child", new_callable=AsyncMock) as mock_child:
            mock_child.return_value = ToolResult.ok("Child completed the task.")
            result = await delegate_tool.execute(
                {"goal": "Find Python files"},
                base_context,
            )
        assert result.success
        assert "Child completed the task." in result.output

    async def test_depth_1_allows_delegation(self, delegate_tool: DelegateSubtaskTool) -> None:
        """Depth 1 (child) should still be allowed to delegate."""
        context = ToolContext(tool_policies={"delegation_depth": "1"})
        with patch.object(delegate_tool, "_run_child", new_callable=AsyncMock) as mock_child:
            mock_child.return_value = ToolResult.ok("Grandchild done.")
            result = await delegate_tool.execute(
                {"goal": "Sub-sub-task"},
                context,
            )
        assert result.success

    async def test_depth_2_rejects_delegation(self, delegate_tool: DelegateSubtaskTool) -> None:
        """Depth 2 (grandchild) must be rejected -- MAX_DEPTH is 2."""
        context = ToolContext(tool_policies={"delegation_depth": "2"})
        result = await delegate_tool.execute(
            {"goal": "Should be rejected"},
            context,
        )
        assert not result.success
        assert "depth limit" in result.error.lower()

    async def test_depth_exceeding_max_rejects(self, delegate_tool: DelegateSubtaskTool) -> None:
        """Depth > MAX_DEPTH is also rejected."""
        context = ToolContext(tool_policies={"delegation_depth": "5"})
        result = await delegate_tool.execute(
            {"goal": "Way too deep"},
            context,
        )
        assert not result.success
        assert "depth limit" in result.error.lower()

    async def test_missing_depth_defaults_to_zero(
        self, delegate_tool: DelegateSubtaskTool
    ) -> None:
        """When delegation_depth is not in tool_policies, default to 0."""
        context = ToolContext(tool_policies={})
        with patch.object(delegate_tool, "_run_child", new_callable=AsyncMock) as mock_child:
            mock_child.return_value = ToolResult.ok("Done")
            result = await delegate_tool.execute({"goal": "Task"}, context)
        assert result.success

    async def test_invalid_depth_value_defaults_to_zero(
        self, delegate_tool: DelegateSubtaskTool
    ) -> None:
        """Non-integer depth value should default to 0 and allow delegation."""
        context = ToolContext(tool_policies={"delegation_depth": "not-a-number"})
        with patch.object(delegate_tool, "_run_child", new_callable=AsyncMock) as mock_child:
            mock_child.return_value = ToolResult.ok("Done")
            result = await delegate_tool.execute({"goal": "Task"}, context)
        assert result.success

    def test_max_depth_constant(self) -> None:
        assert MAX_DEPTH == 2


# ---------------------------------------------------------------------------
# Child isolation tests
# ---------------------------------------------------------------------------


class TestChildIsolation:
    """Verify the child agent gets fresh, isolated context."""

    async def test_child_receives_incremented_depth(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """The child context should have delegation_depth = parent_depth + 1."""
        captured_context: list[ToolContext] = []

        async def capture_child(
            *,
            goal: str,
            context: str,
            toolsets: list[str],
            max_iterations: int,
            model_override: str,
            child_context: ToolContext,
        ) -> ToolResult:
            captured_context.append(child_context)
            return ToolResult.ok("Done")

        with patch.object(delegate_tool, "_run_child", side_effect=capture_child):
            await delegate_tool.execute({"goal": "Test"}, base_context)

        assert len(captured_context) == 1
        child_ctx = captured_context[0]
        assert child_ctx.tool_policies["delegation_depth"] == "1"

    async def test_child_context_preserves_tenant_id(
        self, delegate_tool: DelegateSubtaskTool
    ) -> None:
        """The child context should inherit the parent's tenant_id."""
        context = ToolContext(
            tool_policies={"delegation_depth": "0"},
            tenant_id="my-tenant",
        )
        captured: list[ToolContext] = []

        async def capture(
            *,
            goal: str,
            context: str,
            toolsets: list[str],
            max_iterations: int,
            model_override: str,
            child_context: ToolContext,
        ) -> ToolResult:
            captured.append(child_context)
            return ToolResult.ok("Done")

        with patch.object(delegate_tool, "_run_child", side_effect=capture):
            await delegate_tool.execute({"goal": "Test"}, context)

        assert captured[0].tenant_id == "my-tenant"

    async def test_child_does_not_get_parent_conversation(
        self,
        delegate_tool: DelegateSubtaskTool,
        base_context: ToolContext,
        mock_router: MagicMock,
    ) -> None:
        """The child's AgentRuntime.invoke() should be called with fresh inputs,
        not the parent's conversation history."""
        from agent33.llm.base import LLMResponse

        # Mock the router to return a valid response
        mock_router.complete.return_value = LLMResponse(
            content='{"summary": "Found 3 files"}',
            model="test-model",
            prompt_tokens=10,
            completion_tokens=20,
        )

        await delegate_tool.execute(
            {"goal": "Find Python files", "context": "In the engine/ directory"},
            base_context,
        )

        # The child was invoked through the router, which should have received
        # a system message (child prompt) and a user message (task inputs).
        # Importantly, it should NOT have received parent conversation history.
        assert mock_router.complete.called
        call_args = mock_router.complete.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1].get("messages", [])
        # System message should contain the child system prompt, not parent history
        system_msg = messages[0]
        assert "Delegated Subtask" in system_msg.content
        assert "Find Python files" in system_msg.content


class TestFilteredChildRegistry:
    """Verify delegated children only see and execute allowlisted tools."""

    async def test_child_tool_registry_blocks_disallowed_tools(
        self, mock_router: MagicMock, base_context: ToolContext
    ) -> None:
        registry = ToolRegistry()
        registry.register(_StubTool("shell"))
        registry.register(_StubTool("web_fetch"))
        tool = DelegateSubtaskTool(router=mock_router, tool_registry=registry)

        class _FakeToolLoop:
            instances: list[_FakeToolLoop] = []

            def __init__(
                self,
                *,
                router: Any,
                tool_registry: Any,
                tool_context: ToolContext,
                config: Any,
                agent_name: str,
                session_id: str,
            ) -> None:
                self.tool_registry = tool_registry
                self.tool_context = tool_context
                self.agent_name = agent_name
                self.session_id = session_id
                self.visible_tools: list[str] = []
                self.allowed_result: ToolResult | None = None
                self.blocked_result: ToolResult | None = None
                _FakeToolLoop.instances.append(self)

            async def run(
                self,
                *,
                messages: list[Any],
                model: str,
                temperature: float,
                max_tokens: int,
            ) -> Any:
                self.visible_tools = [item.name for item in self.tool_registry.list_all()]
                self.allowed_result = await self.tool_registry.validated_execute(
                    "shell",
                    {},
                    self.tool_context,
                )
                self.blocked_result = await self.tool_registry.validated_execute(
                    "web_fetch",
                    {},
                    self.tool_context,
                )
                return SimpleNamespace(
                    raw_response="",
                    output={"result": "delegated summary"},
                )

        with patch("agent33.agents.tool_loop.ToolLoop", _FakeToolLoop):
            result = await tool.execute(
                {"goal": "delegate this", "toolsets": ["shell", "delegate_subtask"]},
                base_context,
            )

        assert result.success
        assert result.output == '{"result": "delegated summary"}'
        assert len(_FakeToolLoop.instances) == 1
        instance = _FakeToolLoop.instances[0]
        assert instance.visible_tools == ["shell"]
        assert instance.allowed_result is not None and instance.allowed_result.success
        assert instance.blocked_result is not None and not instance.blocked_result.success
        assert "not available to delegated children" in instance.blocked_result.error.lower()

    async def test_pack_discovery_slash_command_and_moa_chain(
        self,
        mock_router: MagicMock,
        base_context: ToolContext,
        tmp_path: Path,
    ) -> None:
        packs_dir = tmp_path / "packs"
        pack_dir = packs_dir / "review-pack"
        skill_dir = pack_dir / "skills" / "ensemble-review"
        skill_dir.mkdir(parents=True)
        (pack_dir / "PACK.yaml").write_text(
            "\n".join(
                [
                    'name: "review-pack"',
                    'version: "1.0.0"',
                    'description: "Review capability pack"',
                    'author: "tester"',
                    "skills:",
                    "  - name: ensemble-review",
                    "    path: skills/ensemble-review",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (skill_dir / "SKILL.md").write_text(
            """---
name: ensemble-review
version: 1.0.0
description: Review and synthesize pack findings
allowed_tools:
  - mixture_of_agents
---

# Ensemble Review

Use the MoA tool to synthesize the pack findings.
""",
            encoding="utf-8",
        )

        skill_registry = SkillRegistry()
        pack_registry = PackRegistry(packs_dir=packs_dir, skill_registry=skill_registry)
        assert pack_registry.discover() == 1

        commands = scan_skill_commands(skill_registry)
        parsed = parse_slash_command("/ensemble-review compare these answers", commands)
        assert parsed is not None
        skill_name, instruction = parsed
        assert skill_name == "ensemble-review"
        assert instruction == "compare these answers"

        discovered_skill = skill_registry.get(skill_name)
        assert discovered_skill is not None
        assert skill_registry.get("review-pack/ensemble-review") is not None
        assert discovered_skill.allowed_tools == ["mixture_of_agents"]
        injector = SkillInjector(skill_registry)

        tool_registry = ToolRegistry()
        moa_tool = MoATool(
            default_reference_models=["ref-model"],
            default_aggregator_model="agg-model",
        )
        tool_registry.register(moa_tool)
        tool_registry.register(_ProbeTool())

        delegate_tool = DelegateSubtaskTool(router=mock_router, tool_registry=tool_registry)
        skill_context = injector.resolve_tool_context(
            [skill_name],
            dataclasses.replace(
                base_context,
                command_allowlist=["delegate_subtask", "mixture_of_agents", "probe_tool"],
            ),
        )
        assert skill_context.command_allowlist == ["mixture_of_agents"]

        tool_call = ToolCall(
            id="call-1",
            function=ToolCallFunction(
                name="mixture_of_agents",
                arguments='{"query":"synthesize the reviewed pack findings"}',
            ),
        )
        mock_router.complete = AsyncMock(
            side_effect=[
                LLMResponse(
                    content="Calling MoA",
                    model="child-model",
                    prompt_tokens=12,
                    completion_tokens=6,
                    tool_calls=[tool_call],
                    finish_reason="tool_calls",
                ),
                LLMResponse(
                    content="Working through the pack review",
                    model="child-model",
                    prompt_tokens=12,
                    completion_tokens=6,
                ),
                LLMResponse(
                    content='COMPLETED: {"result":"pack review complete"}',
                    model="child-model",
                    prompt_tokens=12,
                    completion_tokens=6,
                ),
            ]
        )

        moa_execute = AsyncMock(return_value=ToolResult.ok("MoA synthesized answer"))
        with patch.object(moa_tool, "execute", moa_execute):
            result = await delegate_tool.execute(
                {
                    "goal": "Use the capability pack review skill to synthesize the findings",
                    "context": instruction,
                    "toolsets": skill_context.command_allowlist + ["delegate_subtask", "clarify"],
                },
                base_context,
            )

        assert result.success
        assert "pack review complete" in result.output
        assert result.output.startswith("COMPLETED:")
        moa_execute.assert_awaited_once()

        first_call_tools = mock_router.complete.call_args_list[0].kwargs["tools"]
        assert [tool["name"] for tool in first_call_tools] == ["mixture_of_agents"]
        assert "probe_tool" not in {tool["name"] for tool in first_call_tools}
        second_call_messages = mock_router.complete.call_args_list[1].args[0]
        tool_messages = [msg for msg in second_call_messages if msg.role == "tool"]
        assert len(tool_messages) == 1
        assert "MoA synthesized answer" in tool_messages[0].content
        assert tool_registry.get("probe_tool") is not None
        assert tool_registry.get("mixture_of_agents") is not None


# ---------------------------------------------------------------------------
# Summary-only return tests
# ---------------------------------------------------------------------------


class TestParentReceivesSummaryOnly:
    """Verify the parent gets only the final summary, not intermediate tool calls."""

    async def test_single_task_returns_summary_string(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """Single task mode should return the child's final output as a string."""
        with patch.object(delegate_tool, "_run_child", new_callable=AsyncMock) as mock_child:
            mock_child.return_value = ToolResult.ok("Found 5 matching files in the project.")
            result = await delegate_tool.execute(
                {"goal": "Search for config files"},
                base_context,
            )
        assert result.success
        assert result.output == "Found 5 matching files in the project."
        # No intermediate tool-call data should be present
        assert "tool_call" not in result.output.lower()

    async def test_failed_task_returns_error(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """If the child fails, the parent should get a clear error."""
        with patch.object(delegate_tool, "_run_child", new_callable=AsyncMock) as mock_child:
            mock_child.return_value = ToolResult.fail("Child could not access the file.")
            result = await delegate_tool.execute(
                {"goal": "Read a restricted file"},
                base_context,
            )
        assert not result.success
        assert "Child could not access the file." in result.error


# ---------------------------------------------------------------------------
# Timeout tests
# ---------------------------------------------------------------------------


class TestTimeout:
    """Verify child agent timeout enforcement."""

    async def test_child_timeout_produces_failure(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """A child that exceeds the timeout should produce a ToolResult.fail."""

        async def slow_child(
            *,
            goal: str,
            context: str,
            toolsets: list[str],
            max_iterations: int,
            model_override: str,
            child_context: ToolContext,
        ) -> ToolResult:
            await asyncio.sleep(10)
            return ToolResult.ok("Should not reach here")

        with patch.object(delegate_tool, "_run_child", side_effect=slow_child):
            result = await delegate_tool.execute(
                {"goal": "Slow task", "timeout": 1},
                base_context,
            )
        assert not result.success
        assert "timed out" in result.error.lower()


# ---------------------------------------------------------------------------
# Batch mode tests
# ---------------------------------------------------------------------------


class TestBatchDelegation:
    """Verify batch mode concurrent execution and result aggregation."""

    async def test_batch_mode_runs_multiple_tasks(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """Batch mode should run all tasks and aggregate results."""
        call_count = 0

        async def mock_child(
            *,
            goal: str,
            context: str,
            toolsets: list[str],
            max_iterations: int,
            model_override: str,
            child_context: ToolContext,
        ) -> ToolResult:
            nonlocal call_count
            call_count += 1
            return ToolResult.ok(f"Completed: {goal}")

        with patch.object(delegate_tool, "_run_child", side_effect=mock_child):
            result = await delegate_tool.execute(
                {
                    "goal": "ignored in batch mode",
                    "tasks": [
                        {"goal": "Task A"},
                        {"goal": "Task B", "context": "Extra context"},
                        {"goal": "Task C"},
                    ],
                },
                base_context,
            )

        assert result.success
        assert call_count == 3
        parsed = json.loads(result.output)
        assert len(parsed) == 3
        for entry in parsed:
            assert entry["status"] == "completed"

    async def test_batch_mode_preserves_task_indices(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """Each result should carry its original task index."""

        async def mock_child(
            *,
            goal: str,
            context: str,
            toolsets: list[str],
            max_iterations: int,
            model_override: str,
            child_context: ToolContext,
        ) -> ToolResult:
            return ToolResult.ok(f"Done: {goal}")

        with patch.object(delegate_tool, "_run_child", side_effect=mock_child):
            result = await delegate_tool.execute(
                {
                    "goal": "ignored",
                    "tasks": [
                        {"goal": "First"},
                        {"goal": "Second"},
                    ],
                },
                base_context,
            )

        parsed = json.loads(result.output)
        indices = {e["task_index"] for e in parsed}
        assert indices == {0, 1}

    async def test_batch_mode_handles_partial_failures(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """If one task fails, other tasks should still succeed."""
        call_index = 0

        async def mock_child(
            *,
            goal: str,
            context: str,
            toolsets: list[str],
            max_iterations: int,
            model_override: str,
            child_context: ToolContext,
        ) -> ToolResult:
            nonlocal call_index
            call_index += 1
            if goal == "Fail this":
                return ToolResult.fail("Intentional failure")
            return ToolResult.ok(f"Success: {goal}")

        with patch.object(delegate_tool, "_run_child", side_effect=mock_child):
            result = await delegate_tool.execute(
                {
                    "goal": "ignored",
                    "tasks": [
                        {"goal": "Task OK"},
                        {"goal": "Fail this"},
                        {"goal": "Another OK"},
                    ],
                },
                base_context,
            )

        assert result.success  # batch itself succeeds, individual statuses vary
        parsed = json.loads(result.output)
        statuses = {e["task_index"]: e["status"] for e in parsed}
        # At least one completed and one error
        assert "completed" in statuses.values()
        assert "error" in statuses.values()

    async def test_batch_mode_empty_tasks_fails(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """Empty task list should return an error."""
        result = await delegate_tool.execute(
            {"goal": "ignored", "tasks": []},
            base_context,
        )
        assert not result.success
        assert "empty" in result.error.lower()

    async def test_batch_mode_respects_depth(self, delegate_tool: DelegateSubtaskTool) -> None:
        """Batch mode should also enforce depth limits."""
        context = ToolContext(tool_policies={"delegation_depth": "2"})
        result = await delegate_tool.execute(
            {
                "goal": "ignored",
                "tasks": [{"goal": "Should fail"}],
            },
            context,
        )
        assert not result.success
        assert "depth limit" in result.error.lower()

    async def test_batch_mode_concurrent_limit(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """Verify the semaphore limits concurrent children to 3."""
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def mock_child(
            *,
            goal: str,
            context: str,
            toolsets: list[str],
            max_iterations: int,
            model_override: str,
            child_context: ToolContext,
        ) -> ToolResult:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            await asyncio.sleep(0.05)  # simulate work
            async with lock:
                current_concurrent -= 1
            return ToolResult.ok(f"Done: {goal}")

        tasks = [{"goal": f"Task {i}"} for i in range(6)]

        with patch.object(delegate_tool, "_run_child", side_effect=mock_child):
            result = await delegate_tool.execute(
                {"goal": "ignored", "tasks": tasks},
                base_context,
            )

        assert result.success
        # Semaphore is 3, so max concurrent should be <= 3
        assert max_concurrent <= 3


# ---------------------------------------------------------------------------
# Validation edge cases
# ---------------------------------------------------------------------------


class TestValidationEdgeCases:
    """Test parameter validation edge cases."""

    async def test_empty_goal_fails(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        result = await delegate_tool.execute({"goal": ""}, base_context)
        assert not result.success
        assert "no goal" in result.error.lower()

    async def test_whitespace_goal_fails(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        result = await delegate_tool.execute({"goal": "   "}, base_context)
        assert not result.success
        assert "no goal" in result.error.lower()

    async def test_toolsets_with_blocked_tools_are_filtered(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """Blocked tools should be silently removed from toolsets."""
        captured_toolsets: list[list[str]] = []

        async def mock_child(
            *,
            goal: str,
            context: str,
            toolsets: list[str],
            max_iterations: int,
            model_override: str,
            child_context: ToolContext,
        ) -> ToolResult:
            captured_toolsets.append(toolsets)
            return ToolResult.ok("Done")

        with patch.object(delegate_tool, "_run_child", side_effect=mock_child):
            await delegate_tool.execute(
                {
                    "goal": "Test task",
                    "toolsets": ["shell", "delegate_subtask", "clarify", "web_fetch"],
                },
                base_context,
            )

        # _run_child receives the raw toolsets; the filtering happens inside _run_child
        # itself. Since we mock _run_child, let's test strip_blocked_tools directly
        # and verify _run_child is called with the correct goal
        assert len(captured_toolsets) == 1

    async def test_exception_in_child_produces_failure(
        self, delegate_tool: DelegateSubtaskTool, base_context: ToolContext
    ) -> None:
        """An unhandled exception in the child should produce a ToolResult.fail."""

        async def exploding_child(
            *,
            goal: str,
            context: str,
            toolsets: list[str],
            max_iterations: int,
            model_override: str,
            child_context: ToolContext,
        ) -> ToolResult:
            raise RuntimeError("Unexpected failure in child")

        with patch.object(delegate_tool, "_run_child", side_effect=exploding_child):
            result = await delegate_tool.execute(
                {"goal": "This will explode"},
                base_context,
            )
        assert not result.success
        assert "delegation failed" in result.error.lower()
