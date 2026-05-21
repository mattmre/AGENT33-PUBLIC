"""Integration tests: hooks wired into agent invoke, tool execute, workflow step."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.hooks.models import (
    HookContext,
    ToolHookContext,
    WorkflowHookContext,
)
from agent33.hooks.protocol import BaseHook, HookAbortError
from agent33.hooks.registry import HookRegistry

# ---------------------------------------------------------------------------
# Test hooks
# ---------------------------------------------------------------------------


class InputModifyingHook(BaseHook):
    """Pre-hook that modifies inputs."""

    async def execute(self, context, call_next):
        if hasattr(context, "inputs"):
            context.inputs["injected_by_hook"] = True
        return await call_next(context)


class AbortingHook(BaseHook):
    """Pre-hook that aborts the chain."""

    async def execute(self, context, call_next):
        context.abort = True
        context.abort_reason = "security_violation"
        return context


class PostResultCapture(BaseHook):
    """Post-hook that captures the result for assertions."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.captured_result: Any = None

    async def execute(self, context, call_next):
        if hasattr(context, "result"):
            self.captured_result = context.result
        return await call_next(context)


# ---------------------------------------------------------------------------
# AgentRuntime integration
# ---------------------------------------------------------------------------


class TestAgentRuntimeHooks:
    async def test_invoke_with_pre_hook_modifies_inputs(self) -> None:
        """Pre-hook can modify agent inputs before LLM call."""
        from agent33.agents.runtime import AgentRuntime  # noqa: F811

        registry = HookRegistry()
        hook = InputModifyingHook(
            name="modifier",
            event_type="agent.invoke.pre",
            priority=100,
        )
        registry.register(hook)

        # Build a minimal mock runtime
        definition = _mock_definition()
        router = _mock_router(response_content='{"result": "ok"}')

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            hook_registry=registry,
            tenant_id="test-tenant",
        )

        result = await runtime.invoke({"query": "hello"})
        assert result.output == {"result": "ok"}

        # Verify the LLM received modified inputs (with injected_by_hook)
        call_args = router.complete.call_args
        user_msg = call_args.args[0][1]  # second message is user
        import json

        user_inputs = json.loads(user_msg.content)
        assert user_inputs.get("injected_by_hook") is True

    async def test_invoke_with_abort_raises_error(self) -> None:
        """Pre-hook abort prevents the LLM call and raises HookAbortError."""
        from agent33.agents.runtime import AgentRuntime

        registry = HookRegistry()
        hook = AbortingHook(
            name="blocker",
            event_type="agent.invoke.pre",
            priority=10,
        )
        registry.register(hook)

        definition = _mock_definition()
        router = _mock_router()

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            hook_registry=registry,
        )

        with pytest.raises(HookAbortError, match="security_violation"):
            await runtime.invoke({"query": "test"})

        # LLM should never have been called
        router.complete.assert_not_called()

    async def test_invoke_post_hook_receives_result(self) -> None:
        """Post-hook sees the completed AgentResult."""
        from agent33.agents.runtime import AgentRuntime

        registry = HookRegistry()
        post_hook = PostResultCapture(
            name="capture",
            event_type="agent.invoke.post",
            priority=500,
        )
        registry.register(post_hook)

        definition = _mock_definition()
        router = _mock_router(response_content='{"answer": "42"}')

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            hook_registry=registry,
        )

        await runtime.invoke({"q": "x"})
        assert post_hook.captured_result is not None
        assert post_hook.captured_result.output == {"answer": "42"}

    async def test_invoke_without_hooks_unchanged(self) -> None:
        """When hook_registry is None, invoke works exactly as before."""
        from agent33.agents.runtime import AgentRuntime

        definition = _mock_definition()
        router = _mock_router(response_content='{"result": "ok"}')

        runtime = AgentRuntime(
            definition=definition,
            router=router,
            hook_registry=None,
        )

        result = await runtime.invoke({"query": "hello"})
        assert result.output == {"result": "ok"}


# ---------------------------------------------------------------------------
# ToolLoop integration
# ---------------------------------------------------------------------------


class TestToolLoopHooks:
    async def test_tool_pre_hook_modifies_arguments(self) -> None:
        """Pre-tool hook can modify arguments before tool execution."""
        from agent33.hooks.models import ToolHookContext

        registry = HookRegistry()

        class ArgModifier(BaseHook):
            async def execute(self, context, call_next):
                if hasattr(context, "arguments"):
                    context.arguments["extra"] = "added"
                return await call_next(context)

        hook = ArgModifier(
            name="arg_mod",
            event_type="tool.execute.pre",
            priority=100,
        )
        registry.register(hook)

        # Build the tool hook context to verify modification
        ctx = ToolHookContext(
            event_type="tool.execute.pre",
            tenant_id="t1",
            metadata={},
            tool_name="shell",
            arguments={"command": "ls"},
        )

        runner = registry.get_chain_runner("tool.execute.pre", "t1")
        result = await runner.run(ctx)
        assert result.arguments["extra"] == "added"
        assert result.arguments["command"] == "ls"

    async def test_tool_pre_hook_abort(self) -> None:
        """Pre-tool hook abort sets abort flag."""
        registry = HookRegistry()
        hook = AbortingHook(
            name="tool_block",
            event_type="tool.execute.pre",
            priority=10,
        )
        registry.register(hook)

        ctx = ToolHookContext(
            event_type="tool.execute.pre",
            tenant_id="",
            metadata={},
            tool_name="shell",
            arguments={"command": "rm -rf /"},
        )

        runner = registry.get_chain_runner("tool.execute.pre", "")
        result = await runner.run(ctx)
        assert result.abort is True


# ---------------------------------------------------------------------------
# WorkflowExecutor integration
# ---------------------------------------------------------------------------


class TestWorkflowHooks:
    async def test_workflow_step_pre_hook(self) -> None:
        """Pre-step hook can modify resolved inputs."""
        registry = HookRegistry()
        hook = InputModifyingHook(
            name="wf_input_mod",
            event_type="workflow.step.pre",
            priority=100,
        )
        registry.register(hook)

        ctx = WorkflowHookContext(
            event_type="workflow.step.pre",
            tenant_id="t1",
            metadata={},
            workflow_name="deploy",
            step_id="step-1",
            step_action="invoke_agent",
            inputs={"param": "value"},
        )

        runner = registry.get_chain_runner("workflow.step.pre", "t1")
        result = await runner.run(ctx)
        assert result.inputs["injected_by_hook"] is True
        assert result.inputs["param"] == "value"

    async def test_workflow_step_abort(self) -> None:
        """Pre-step hook abort prevents step execution."""
        registry = HookRegistry()
        hook = AbortingHook(
            name="wf_block",
            event_type="workflow.step.pre",
            priority=10,
        )
        registry.register(hook)

        ctx = WorkflowHookContext(
            event_type="workflow.step.pre",
            tenant_id="",
            metadata={},
            workflow_name="deploy",
            step_id="step-1",
            step_action="invoke_agent",
            inputs={},
        )

        runner = registry.get_chain_runner("workflow.step.pre", "")
        result = await runner.run(ctx)
        assert result.abort is True
        assert result.abort_reason == "security_violation"


# ---------------------------------------------------------------------------
# Multi-tenant hook isolation
# ---------------------------------------------------------------------------


class TestMultiTenantIsolation:
    async def test_tenant_hooks_isolated(self) -> None:
        """Tenant-specific hooks only fire for their tenant."""
        registry = HookRegistry()

        class TenantMarker(BaseHook):
            async def execute(self, context, call_next):
                context.metadata[f"ran_{self.tenant_id}"] = True
                return await call_next(context)

        sys_hook = TenantMarker(
            name="sys", event_type="agent.invoke.pre", priority=10, tenant_id=""
        )
        acme_hook = TenantMarker(
            name="acme", event_type="agent.invoke.pre", priority=20, tenant_id="acme"
        )
        other_hook = TenantMarker(
            name="other", event_type="agent.invoke.pre", priority=30, tenant_id="other"
        )
        registry.register(sys_hook)
        registry.register(acme_hook)
        registry.register(other_hook)

        # Run as acme tenant
        ctx = HookContext(event_type="agent.invoke.pre", tenant_id="acme", metadata={})
        runner = registry.get_chain_runner("agent.invoke.pre", "acme")
        result = await runner.run(ctx)

        # System hook and acme hook should have run, other should NOT
        assert result.metadata.get("ran_") is True  # system hook
        assert result.metadata.get("ran_acme") is True
        assert result.metadata.get("ran_other") is None


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _mock_definition() -> MagicMock:
    """Create a minimal agent definition mock."""
    defn = MagicMock()
    defn.name = "test-agent"
    defn.inputs = {}
    defn.outputs = {"result": MagicMock(type="string", description="result")}
    defn.constraints = MagicMock(
        max_tokens=1000,
        max_retries=0,
        timeout_seconds=30,
    )
    defn.capabilities = []
    defn.spec_capabilities = []
    defn.governance = MagicMock(
        scope="",
        commands="",
        network="",
        approval_required=[],
        tool_policies={},
    )
    defn.autonomy_level = MagicMock(value="full")
    defn.ownership = MagicMock(owner="", escalation_target="")
    defn.dependencies = []
    defn.skills = []
    defn.description = "test"
    defn.agent_id = ""
    return defn


def _mock_router(response_content: str = '{"result": "ok"}') -> MagicMock:
    """Create a minimal model router mock."""
    response = MagicMock()
    response.content = response_content
    response.total_tokens = 100
    response.model = "test-model"

    router = MagicMock()
    router.complete = AsyncMock(return_value=response)
    return router
