"""Tests for hook framework data models."""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from agent33.hooks.models import (
    AgentHookContext,
    HookChainResult,
    HookContext,
    HookDefinition,
    HookEventType,
    HookExecutionLog,
    HookResult,
    RequestHookContext,
    ToolHookContext,
    WorkflowHookContext,
)


class TestHookEventType:
    """Tests for HookEventType enum values."""

    def test_event_type_values(self) -> None:
        assert HookEventType.AGENT_INVOKE_PRE == "agent.invoke.pre"
        assert HookEventType.AGENT_INVOKE_POST == "agent.invoke.post"
        assert HookEventType.TOOL_EXECUTE_PRE == "tool.execute.pre"
        assert HookEventType.TOOL_EXECUTE_POST == "tool.execute.post"
        assert HookEventType.WORKFLOW_STEP_PRE == "workflow.step.pre"
        assert HookEventType.WORKFLOW_STEP_POST == "workflow.step.post"
        assert HookEventType.REQUEST_PRE == "request.pre"
        assert HookEventType.REQUEST_POST == "request.post"

    def test_phase44_has_12_event_types(self) -> None:
        assert len(HookEventType) == 12


class TestHookContext:
    """Tests for base HookContext dataclass."""

    def test_default_fields(self) -> None:
        ctx = HookContext(
            event_type="agent.invoke.pre",
            tenant_id="tenant-1",
        )
        assert ctx.event_type == "agent.invoke.pre"
        assert ctx.tenant_id == "tenant-1"
        assert ctx.metadata == {}
        assert ctx.abort is False
        assert ctx.abort_reason == ""
        assert ctx.results == []

    def test_abort_mutation(self) -> None:
        ctx = HookContext(event_type="test", tenant_id="")
        ctx.abort = True
        ctx.abort_reason = "blocked"
        assert ctx.abort is True
        assert ctx.abort_reason == "blocked"

    def test_results_accumulation(self) -> None:
        ctx = HookContext(event_type="test", tenant_id="")
        r1 = HookResult(hook_name="h1", success=True, duration_ms=5.0)
        r2 = HookResult(hook_name="h2", success=False, error="fail", duration_ms=3.0)
        ctx.results.append(r1)
        ctx.results.append(r2)
        assert len(ctx.results) == 2
        assert ctx.results[0].hook_name == "h1"
        assert ctx.results[1].success is False

    def test_uses_slots(self) -> None:
        assert dataclasses.fields(HookContext)[0].name == "event_type"
        # slots=True means __slots__ is used
        ctx = HookContext(event_type="test", tenant_id="")
        assert hasattr(ctx, "__slots__")


class TestAgentHookContext:
    """Tests for AgentHookContext with agent-specific fields."""

    def test_inherits_base_fields(self) -> None:
        ctx = AgentHookContext(
            event_type="agent.invoke.pre",
            tenant_id="t1",
            agent_name="code-worker",
        )
        assert ctx.event_type == "agent.invoke.pre"
        assert ctx.tenant_id == "t1"
        assert ctx.agent_name == "code-worker"

    def test_default_agent_fields(self) -> None:
        ctx = AgentHookContext(event_type="agent.invoke.pre", tenant_id="")
        assert ctx.agent_name == ""
        assert ctx.agent_definition is None
        assert ctx.inputs == {}
        assert ctx.system_prompt == ""
        assert ctx.model == ""
        assert ctx.result is None
        assert ctx.duration_ms == 0.0

    def test_inputs_can_be_modified(self) -> None:
        ctx = AgentHookContext(
            event_type="agent.invoke.pre",
            tenant_id="",
            inputs={"query": "original"},
        )
        ctx.inputs["query"] = "modified"
        assert ctx.inputs["query"] == "modified"


class TestToolHookContext:
    """Tests for ToolHookContext with tool-specific fields."""

    def test_tool_fields(self) -> None:
        ctx = ToolHookContext(
            event_type="tool.execute.pre",
            tenant_id="",
            tool_name="shell",
            arguments={"command": "ls"},
        )
        assert ctx.tool_name == "shell"
        assert ctx.arguments == {"command": "ls"}
        assert ctx.tool_context is None
        assert ctx.result is None


class TestWorkflowHookContext:
    """Tests for WorkflowHookContext with workflow-specific fields."""

    def test_workflow_fields(self) -> None:
        ctx = WorkflowHookContext(
            event_type="workflow.step.pre",
            tenant_id="",
            workflow_name="deploy",
            step_id="step-1",
            step_action="invoke_agent",
        )
        assert ctx.workflow_name == "deploy"
        assert ctx.step_id == "step-1"
        assert ctx.step_action == "invoke_agent"
        assert ctx.state == {}


class TestRequestHookContext:
    """Tests for RequestHookContext with HTTP-specific fields."""

    def test_request_fields(self) -> None:
        ctx = RequestHookContext(
            event_type="request.pre",
            tenant_id="",
            method="POST",
            path="/v1/agents/code-worker/invoke",
            headers={"content-type": "application/json"},
        )
        assert ctx.method == "POST"
        assert ctx.path == "/v1/agents/code-worker/invoke"
        assert ctx.status_code == 0  # not yet set
        assert ctx.body == b""


class TestHookResult:
    """Tests for HookResult frozen dataclass."""

    def test_success_result(self) -> None:
        r = HookResult(hook_name="metrics", success=True, duration_ms=12.5)
        assert r.hook_name == "metrics"
        assert r.success is True
        assert r.error == ""
        assert r.data == {}
        assert r.duration_ms == 12.5

    def test_failure_result(self) -> None:
        r = HookResult(hook_name="audit", success=False, error="timeout", duration_ms=200.0)
        assert r.success is False
        assert r.error == "timeout"

    def test_frozen_immutable(self) -> None:
        r = HookResult(hook_name="test", success=True)
        with pytest.raises(dataclasses.FrozenInstanceError):
            r.success = False  # type: ignore[misc]


class TestHookChainResult:
    """Tests for HookChainResult aggregate."""

    def test_all_succeeded_true(self) -> None:
        r = HookChainResult(
            event_type="test",
            hook_results=[
                HookResult(hook_name="a", success=True),
                HookResult(hook_name="b", success=True),
            ],
        )
        assert r.all_succeeded is True
        assert r.hook_count == 2

    def test_all_succeeded_false(self) -> None:
        r = HookChainResult(
            event_type="test",
            hook_results=[
                HookResult(hook_name="a", success=True),
                HookResult(hook_name="b", success=False, error="oops"),
            ],
        )
        assert r.all_succeeded is False

    def test_empty_results(self) -> None:
        r = HookChainResult(event_type="test", hook_results=[])
        assert r.all_succeeded is True
        assert r.hook_count == 0

    def test_aborted_chain(self) -> None:
        r = HookChainResult(
            event_type="test",
            hook_results=[],
            aborted=True,
            abort_reason="security block",
            total_duration_ms=5.0,
        )
        assert r.aborted is True
        assert r.abort_reason == "security block"


class TestHookDefinition:
    """Tests for HookDefinition Pydantic model."""

    def test_basic_creation(self) -> None:
        d = HookDefinition(
            name="my-hook",
            event_type=HookEventType.AGENT_INVOKE_PRE,
            handler_ref="agent33.hooks.builtins.MetricsHook",
        )
        assert d.name == "my-hook"
        assert d.event_type == HookEventType.AGENT_INVOKE_PRE
        assert d.priority == 100
        assert d.timeout_ms == 200.0
        assert d.enabled is True
        assert d.tenant_id == ""
        assert d.fail_mode == "open"
        assert d.tags == []
        assert d.hook_id.startswith("hook_")

    def test_priority_bounds(self) -> None:
        d = HookDefinition(
            name="sec",
            event_type=HookEventType.TOOL_EXECUTE_PRE,
            handler_ref="test",
            priority=0,
        )
        assert d.priority == 0

        d2 = HookDefinition(
            name="debug",
            event_type=HookEventType.TOOL_EXECUTE_PRE,
            handler_ref="test",
            priority=1000,
        )
        assert d2.priority == 1000

    def test_invalid_priority_below(self) -> None:
        with pytest.raises(ValueError):
            HookDefinition(
                name="bad",
                event_type=HookEventType.TOOL_EXECUTE_PRE,
                handler_ref="test",
                priority=-1,
            )

    def test_invalid_priority_above(self) -> None:
        with pytest.raises(ValueError):
            HookDefinition(
                name="bad",
                event_type=HookEventType.TOOL_EXECUTE_PRE,
                handler_ref="test",
                priority=1001,
            )

    def test_timestamps_auto_set(self) -> None:
        d = HookDefinition(
            name="ts",
            event_type=HookEventType.REQUEST_PRE,
            handler_ref="test",
        )
        assert isinstance(d.created_at, datetime)
        assert d.created_at.tzinfo is not None

    def test_serialization(self) -> None:
        d = HookDefinition(
            name="ser",
            event_type=HookEventType.WORKFLOW_STEP_POST,
            handler_ref="test.mod.Class",
            config={"key": "value"},
            tags=["custom"],
        )
        data = d.model_dump(mode="json")
        assert data["name"] == "ser"
        assert data["event_type"] == "workflow.step.post"
        assert data["config"] == {"key": "value"}
        assert data["tags"] == ["custom"]


class TestHookExecutionLog:
    """Tests for HookExecutionLog Pydantic model."""

    def test_basic_creation(self) -> None:
        log = HookExecutionLog(
            event_type="agent.invoke.pre",
            tenant_id="acme",
            hook_results=[{"hook_name": "h1", "success": True}],
            total_duration_ms=42.5,
        )
        assert log.event_type == "agent.invoke.pre"
        assert log.tenant_id == "acme"
        assert log.aborted is False
        assert len(log.hook_results) == 1
        assert log.total_duration_ms == 42.5
        assert isinstance(log.timestamp, datetime)
