"""E2E: Hook registration -> agent invocation -> hook chain execution.

These tests exercise the hook framework's integration with the agent runtime
through the HTTP API:
1. Pre-hooks mutate agent inputs before the LLM call
2. Post-hooks receive the agent result
3. Hook abort prevents agent execution
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agent33.agents.definition import (
    AgentConstraints,
    AgentDefinition,
    AgentParameter,
    AgentRole,
)
from agent33.hooks.models import AgentHookContext, HookEventType
from agent33.hooks.protocol import BaseHook
from agent33.llm.base import LLMResponse
from agent33.security.auth import create_access_token

pytestmark = pytest.mark.e2e


def _admin_token() -> str:
    return create_access_token("e2e-hook-user", scopes=["admin"])


class InputMutatingHook(BaseHook):
    """Test hook that mutates agent inputs by adding a marker."""

    def __init__(self, marker: str = "[HOOKED]") -> None:
        super().__init__(
            name="e2e-input-mutator",
            event_type=HookEventType.AGENT_INVOKE_PRE.value,
            priority=50,
            enabled=True,
            tenant_id="",
        )
        self._marker = marker
        self.invocations: list[dict[str, Any]] = []

    async def execute(self, context, call_next):
        """Prepend marker to the prompt input."""
        if isinstance(context, AgentHookContext):
            original = context.inputs.get("prompt", "")
            context.inputs["prompt"] = f"{self._marker} {original}"
            self.invocations.append(
                {
                    "agent_name": context.agent_name,
                    "original_prompt": original,
                    "mutated_prompt": context.inputs["prompt"],
                }
            )
        return await call_next(context)


class ResultCapturingHook(BaseHook):
    """Test hook that captures agent results in post-invoke."""

    def __init__(self) -> None:
        super().__init__(
            name="e2e-result-capturer",
            event_type=HookEventType.AGENT_INVOKE_POST.value,
            priority=50,
            enabled=True,
            tenant_id="",
        )
        self.captured_results: list[Any] = []

    async def execute(self, context, call_next):
        """Record the agent result from the context."""
        if isinstance(context, AgentHookContext) and context.result is not None:
            self.captured_results.append(
                {
                    "agent_name": context.agent_name,
                    "output": context.result.output if hasattr(context.result, "output") else None,
                    "model": context.result.model if hasattr(context.result, "model") else None,
                }
            )
        return await call_next(context)


class AbortingHook(BaseHook):
    """Test hook that aborts the agent invocation."""

    def __init__(self) -> None:
        super().__init__(
            name="e2e-aborter",
            event_type=HookEventType.AGENT_INVOKE_PRE.value,
            priority=10,  # High priority (low number runs first)
            enabled=True,
            tenant_id="",
        )

    async def execute(self, context, call_next):
        """Abort the invocation with a specific reason."""
        context.abort = True
        context.abort_reason = "E2E abort test: blocked by hook"
        return context


def _register_test_agent(app, name: str = "e2e-hook-agent") -> AgentDefinition:
    """Register a test agent on the app and return the definition."""
    agent_def = AgentDefinition(
        name=name,
        version="1.0.0",
        role=AgentRole.WORKER,
        description="Hook test agent",
        inputs={"prompt": AgentParameter(type="string", description="input")},
        outputs={"result": AgentParameter(type="string", description="output")},
        constraints=AgentConstraints(max_tokens=128, timeout_seconds=10, max_retries=0),
    )
    app.state.agent_registry.register(agent_def)
    return agent_def


class TestPreHookMutatesInput:
    """Pre-hook mutates inputs before they reach the LLM."""

    def test_pre_hook_mutates_input_reaching_llm(self, e2e_client):
        """Register a pre-hook, invoke agent via HTTP, verify the hook ran.

        This uses the REAL AgentRuntime (not mocked) so that the pre-hook
        chain executes inside invoke(). The LLM provider is mocked to
        return a canned response. We verify:
        1. The hook's invocation log records the original and mutated input
        2. The response still succeeds (hook did not break the pipeline)
        3. The model_router.complete() was called (proving we reached the LLM)
        """
        app, client, _ = e2e_client
        token = _admin_token()

        _register_test_agent(app, "e2e-prehook-agent")

        # Install the mutating hook
        mutator = InputMutatingHook(marker="[E2E-HOOK]")
        hook_registry = getattr(app.state, "hook_registry", None)
        if hook_registry is None:
            pytest.skip("Hook registry not initialized")
        hook_registry.register(mutator)

        mock_llm_response = LLMResponse(
            content='{"result": "hooked response"}',
            model="mock-model",
            prompt_tokens=10,
            completion_tokens=10,
        )

        try:
            with patch.object(
                app.state.model_router,
                "complete",
                new_callable=AsyncMock,
                return_value=mock_llm_response,
            ) as mock_complete:
                resp = client.post(
                    "/v1/agents/e2e-prehook-agent/invoke",
                    json={"inputs": {"prompt": "test input"}},
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert resp.status_code == 200
            body = resp.json()
            assert body["output"]["result"] == "hooked response"

            # The hook's own invocation log confirms it ran and mutated
            assert len(mutator.invocations) >= 1
            last = mutator.invocations[-1]
            assert last["original_prompt"] == "test input"
            assert "[E2E-HOOK]" in last["mutated_prompt"]
            assert last["agent_name"] == "e2e-prehook-agent"

            # The LLM was actually called (the hook didn't break the chain)
            mock_complete.assert_awaited_once()

            # Verify the user content sent to the LLM contains the mutated input
            call_args = mock_complete.call_args
            messages = call_args[0][0]  # first positional arg
            user_msg = next(m for m in messages if m.role == "user")
            assert "[E2E-HOOK]" in user_msg.content
        finally:
            hook_registry.deregister("e2e-input-mutator")


class TestPostHookCapturesResult:
    """Post-hook receives the completed agent result."""

    def test_post_hook_receives_agent_result(self, e2e_client):
        """Register a post-hook, invoke agent with real runtime, verify capture.

        Uses real AgentRuntime with mocked LLM. The post-hook fires after
        the LLM response is processed and captures the AgentResult.

        Verifies:
        1. Post-hook fires after invocation completes
        2. The captured result contains the correct output and model
        3. The agent name is passed through to the hook context
        """
        app, client, _ = e2e_client
        token = _admin_token()

        _register_test_agent(app, "e2e-posthook-agent")

        # Install the capturing hook
        capturer = ResultCapturingHook()
        hook_registry = getattr(app.state, "hook_registry", None)
        if hook_registry is None:
            pytest.skip("Hook registry not initialized")
        hook_registry.register(capturer)

        mock_llm_response = LLMResponse(
            content='{"result": "post-hook captured value"}',
            model="mock-model",
            prompt_tokens=10,
            completion_tokens=15,
        )

        try:
            with patch.object(
                app.state.model_router,
                "complete",
                new_callable=AsyncMock,
                return_value=mock_llm_response,
            ):
                resp = client.post(
                    "/v1/agents/e2e-posthook-agent/invoke",
                    json={"inputs": {"prompt": "capture this"}},
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert resp.status_code == 200

            # Verify the post-hook captured the result
            assert len(capturer.captured_results) >= 1
            captured = capturer.captured_results[-1]
            assert captured["agent_name"] == "e2e-posthook-agent"
            assert captured["output"]["result"] == "post-hook captured value"
            assert captured["model"] == "mock-model"
        finally:
            hook_registry.deregister("e2e-result-capturer")


class TestHookAbortPreventsExecution:
    """An aborting pre-hook prevents the agent from executing."""

    def test_abort_hook_returns_403(self, e2e_client):
        """Register an aborting hook, invoke agent, verify 403 response.

        Uses real AgentRuntime. The aborting hook fires before the LLM
        call and sets context.abort=True. The runtime raises HookAbortError,
        and the route returns 403 with the abort reason.

        Verifies:
        1. The aborting hook runs before the LLM call
        2. HookAbortError is raised by the runtime
        3. The route catches HookAbortError and returns 403
        4. The abort reason is included in the response detail
        """
        app, client, _ = e2e_client
        token = _admin_token()

        _register_test_agent(app, "e2e-abort-agent")

        # Install the aborting hook
        aborter = AbortingHook()
        hook_registry = getattr(app.state, "hook_registry", None)
        if hook_registry is None:
            pytest.skip("Hook registry not initialized")
        hook_registry.register(aborter)

        mock_llm_response = LLMResponse(
            content='{"result": "should not reach here"}',
            model="mock",
            prompt_tokens=10,
            completion_tokens=10,
        )

        try:
            with patch.object(
                app.state.model_router,
                "complete",
                new_callable=AsyncMock,
                return_value=mock_llm_response,
            ) as mock_complete:
                resp = client.post(
                    "/v1/agents/e2e-abort-agent/invoke",
                    json={"inputs": {"prompt": "should be aborted"}},
                    headers={"Authorization": f"Bearer {token}"},
                )

            assert resp.status_code == 403
            assert "E2E abort test" in resp.json()["detail"]

            # The LLM should NOT have been called (abort happened before it)
            mock_complete.assert_not_awaited()
        finally:
            hook_registry.deregister("e2e-aborter")
