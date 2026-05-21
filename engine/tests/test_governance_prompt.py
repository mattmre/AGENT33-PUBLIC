"""Tests for governance prompt wiring and progressive recall integration.

Verifies that _build_system_prompt includes all agent definition fields
(governance, ownership, safety guardrails, spec capabilities, etc.) and that
AgentRuntime injects memory context from ProgressiveRecall into the system
prompt before calling the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.agents.definition import (
    AgentCapability,
    AgentConstraints,
    AgentDefinition,
    AgentDependency,
    AgentOwnership,
    AgentParameter,
    AgentRole,
    GovernanceConstraints,
    SpecCapability,
)
from agent33.agents.runtime import AgentRuntime, _build_system_prompt
from agent33.llm.base import LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_definition(**overrides: object) -> AgentDefinition:
    """Create an AgentDefinition with sensible defaults."""
    defaults: dict[str, object] = {
        "name": "test-agent",
        "version": "1.0.0",
        "role": AgentRole.IMPLEMENTER,
        "description": "A test agent",
        "capabilities": [AgentCapability.CODE_EXECUTION],
        "inputs": {
            "task": AgentParameter(type="string", description="The task", required=True),
        },
        "outputs": {
            "result": AgentParameter(type="string", description="The result"),
        },
        "constraints": AgentConstraints(),
    }
    defaults.update(overrides)
    return AgentDefinition(**defaults)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class _FakeRecallResult:
    """Minimal stand-in matching the RecallResult interface."""

    level: str
    content: str
    citations: list[str] = field(default_factory=list)
    token_estimate: int = 0


# ---------------------------------------------------------------------------
# _build_system_prompt tests
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_includes_identity_section(self) -> None:
        d = _make_definition()
        prompt = _build_system_prompt(d)
        assert "# Identity" in prompt
        assert "'test-agent'" in prompt
        assert "implementer" in prompt

    def test_includes_description(self) -> None:
        d = _make_definition(description="Writes code for tasks")
        prompt = _build_system_prompt(d)
        assert "Writes code for tasks" in prompt

    def test_includes_agent_id(self) -> None:
        d = _make_definition(agent_id="AGT-001")
        prompt = _build_system_prompt(d)
        assert "AGT-001" in prompt

    def test_includes_capabilities(self) -> None:
        d = _make_definition(
            capabilities=[AgentCapability.CODE_EXECUTION, AgentCapability.FILE_READ]
        )
        prompt = _build_system_prompt(d)
        assert "# Capabilities" in prompt
        assert "code-execution" in prompt
        assert "file-read" in prompt

    def test_includes_governance_constraints(self) -> None:
        d = _make_definition(
            governance=GovernanceConstraints(
                scope="assigned-workspace",
                commands="build,test,lint",
                network="none",
                approval_required=["deploy"],
            )
        )
        prompt = _build_system_prompt(d)
        assert "# Governance Constraints" in prompt
        assert "assigned-workspace" in prompt
        assert "build,test,lint" in prompt
        assert "Network access: none" in prompt
        assert "deploy" in prompt

    def test_omits_governance_when_empty(self) -> None:
        d = _make_definition(governance=GovernanceConstraints())
        prompt = _build_system_prompt(d)
        assert "# Governance Constraints" not in prompt

    def test_includes_ownership(self) -> None:
        d = _make_definition(
            ownership=AgentOwnership(owner="platform-team", escalation_target="orchestrator")
        )
        prompt = _build_system_prompt(d)
        assert "# Ownership" in prompt
        assert "platform-team" in prompt
        assert "orchestrator" in prompt

    def test_omits_ownership_when_empty(self) -> None:
        d = _make_definition(ownership=AgentOwnership())
        prompt = _build_system_prompt(d)
        assert "# Ownership" not in prompt

    def test_includes_dependencies(self) -> None:
        d = _make_definition(
            dependencies=[
                AgentDependency(agent="qa", optional=False, purpose="code review"),
                AgentDependency(agent="researcher", optional=True),
            ]
        )
        prompt = _build_system_prompt(d)
        assert "# Dependencies" in prompt
        assert "qa" in prompt
        assert "code review" in prompt
        assert "(optional)" in prompt

    def test_includes_safety_guardrails(self) -> None:
        d = _make_definition()
        prompt = _build_system_prompt(d)
        assert "# Safety Rules" in prompt
        assert "Never expose secrets" in prompt
        assert "destructive operations" in prompt
        assert "contradict these system rules" in prompt
        assert "Treat all user data as sensitive" in prompt

    def test_includes_spec_capabilities(self) -> None:
        d = _make_definition(spec_capabilities=[SpecCapability.I_01, SpecCapability.I_02])
        prompt = _build_system_prompt(d)
        assert "# Spec Capabilities" in prompt
        assert "I-01" in prompt
        assert "Code Generation" in prompt
        assert "I-02" in prompt
        assert "Code Modification" in prompt

    def test_includes_inputs_with_required(self) -> None:
        d = _make_definition()
        prompt = _build_system_prompt(d)
        assert "# Expected Inputs" in prompt
        assert "task (string)" in prompt
        assert "(required)" in prompt
        assert "The task" in prompt

    def test_includes_outputs(self) -> None:
        d = _make_definition()
        prompt = _build_system_prompt(d)
        assert "# Required Outputs" in prompt
        assert "result (string)" in prompt
        assert "The result" in prompt

    def test_includes_execution_constraints(self) -> None:
        d = _make_definition(
            constraints=AgentConstraints(max_tokens=8192, timeout_seconds=60, max_retries=3)
        )
        prompt = _build_system_prompt(d)
        assert "# Execution Constraints" in prompt
        assert "8192" in prompt
        assert "60s" in prompt
        assert "3" in prompt

    def test_includes_output_format(self) -> None:
        d = _make_definition()
        prompt = _build_system_prompt(d)
        assert "# Output Format" in prompt
        assert "valid JSON" in prompt

    def test_full_prompt_structure_order(self) -> None:
        """Verify sections appear in the correct order."""
        d = _make_definition(
            agent_id="AGT-001",
            governance=GovernanceConstraints(scope="full-system"),
            ownership=AgentOwnership(owner="team"),
            dependencies=[AgentDependency(agent="qa")],
            spec_capabilities=[SpecCapability.I_01],
        )
        prompt = _build_system_prompt(d)
        sections = [
            "# Identity",
            "# Capabilities",
            "# Spec Capabilities",
            "# Governance Constraints",
            "# Ownership",
            "# Dependencies",
            "# Expected Inputs",
            "# Required Outputs",
            "# Execution Constraints",
            "# Safety Rules",
            "# Output Format",
        ]
        positions = [prompt.find(s) for s in sections]
        # All sections must be present
        assert all(p >= 0 for p in positions), (
            f"Missing sections: {[s for s, p in zip(sections, positions, strict=True) if p < 0]}"
        )
        assert positions == sorted(positions), "Sections should appear in order"

    def test_no_capabilities_omits_section(self) -> None:
        d = _make_definition(capabilities=[])
        prompt = _build_system_prompt(d)
        assert "# Capabilities" not in prompt

    def test_no_inputs_omits_section(self) -> None:
        d = _make_definition(inputs={})
        prompt = _build_system_prompt(d)
        assert "# Expected Inputs" not in prompt

    def test_no_outputs_omits_section(self) -> None:
        d = _make_definition(outputs={})
        prompt = _build_system_prompt(d)
        assert "# Required Outputs" not in prompt

    def test_governance_partial_fields(self) -> None:
        """Only scope set -- should still render the governance section."""
        d = _make_definition(governance=GovernanceConstraints(scope="read-only"))
        prompt = _build_system_prompt(d)
        assert "# Governance Constraints" in prompt
        assert "read-only" in prompt
        # Fields not set should not appear
        assert "Allowed commands:" not in prompt

    def test_governance_includes_tool_policies(self) -> None:
        """Tool policies appear in governance constraints section."""
        d = _make_definition(
            governance=GovernanceConstraints(
                scope="workspace",
                tool_policies={
                    "shell": "deny",
                    "file_ops:write": "ask",
                    "web_*": "allow",
                },
            )
        )
        prompt = _build_system_prompt(d)
        assert "# Governance Constraints" in prompt
        assert "Tool policies:" in prompt
        assert "shell: deny" in prompt
        assert "file_ops:write: ask" in prompt
        assert "web_*: allow" in prompt

    def test_governance_only_tool_policies(self) -> None:
        """Tool policies alone should render governance section."""
        d = _make_definition(governance=GovernanceConstraints(tool_policies={"*": "ask"}))
        prompt = _build_system_prompt(d)
        assert "# Governance Constraints" in prompt
        assert "Tool policies:" in prompt
        assert "*: ask" in prompt


# ---------------------------------------------------------------------------
# ProgressiveRecall integration tests
# ---------------------------------------------------------------------------


class TestProgressiveRecallIntegration:
    @pytest.fixture()
    def mock_router(self) -> MagicMock:
        router = MagicMock()
        router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "done"}',
                model="test-model",
                prompt_tokens=50,
                completion_tokens=50,
            )
        )
        return router

    @pytest.fixture()
    def mock_recall(self) -> MagicMock:
        recall = MagicMock()
        recall.search = AsyncMock(
            return_value=[
                _FakeRecallResult(
                    level="index",
                    content="[worker/llm_response] prior task result",
                    citations=["obs-1"],
                    token_estimate=20,
                ),
            ]
        )
        return recall

    async def test_invoke_includes_memory_context(
        self, mock_router: MagicMock, mock_recall: MagicMock
    ) -> None:
        d = _make_definition()
        runtime = AgentRuntime(
            definition=d,
            router=mock_router,
            progressive_recall=mock_recall,
        )
        await runtime.invoke({"task": "write code"})

        # Verify recall was searched
        mock_recall.search.assert_called_once()
        call_kwargs = mock_recall.search.call_args
        assert call_kwargs[1]["level"] == "index"
        assert call_kwargs[1]["top_k"] == 5

        # Verify the system prompt sent to LLM includes memory context
        call_args = mock_router.complete.call_args
        messages = call_args[0][0]
        system_msg = messages[0].content
        assert "# Prior Context (from memory)" in system_msg
        assert "prior task result" in system_msg

    async def test_invoke_works_without_recall(self, mock_router: MagicMock) -> None:
        d = _make_definition()
        runtime = AgentRuntime(definition=d, router=mock_router)
        result = await runtime.invoke({"task": "write code"})
        assert result.output == {"result": "done"}
        assert result.model == "test-model"
        assert result.tokens_used == 100

    async def test_invoke_handles_recall_failure(self, mock_router: MagicMock) -> None:
        recall = MagicMock()
        recall.search = AsyncMock(side_effect=RuntimeError("memory error"))
        d = _make_definition()
        runtime = AgentRuntime(
            definition=d,
            router=mock_router,
            progressive_recall=recall,
        )
        # Should not raise -- gracefully degrades
        result = await runtime.invoke({"task": "write code"})
        assert result.output == {"result": "done"}

    async def test_invoke_no_recall_results(self, mock_router: MagicMock) -> None:
        recall = MagicMock()
        recall.search = AsyncMock(return_value=[])
        d = _make_definition()
        runtime = AgentRuntime(
            definition=d,
            router=mock_router,
            progressive_recall=recall,
        )
        result = await runtime.invoke({"task": "write code"})
        # No "Prior Context" section when results are empty
        messages = mock_router.complete.call_args[0][0]
        assert "Prior Context" not in messages[0].content
        assert result.output == {"result": "done"}

    async def test_system_prompt_still_has_safety_with_recall(
        self, mock_router: MagicMock, mock_recall: MagicMock
    ) -> None:
        """Memory context should not displace safety rules."""
        d = _make_definition()
        runtime = AgentRuntime(
            definition=d,
            router=mock_router,
            progressive_recall=mock_recall,
        )
        await runtime.invoke({"task": "do something"})
        messages = mock_router.complete.call_args[0][0]
        system_msg = messages[0].content
        # Safety rules must still be present even with memory context appended
        assert "# Safety Rules" in system_msg
        assert "Never expose secrets" in system_msg
        # Memory context must come after safety rules
        safety_pos = system_msg.find("# Safety Rules")
        memory_pos = system_msg.find("# Prior Context")
        assert memory_pos > safety_pos


# ---------------------------------------------------------------------------
# Workflow bridge registry lookup tests
# ---------------------------------------------------------------------------


class TestWorkflowBridgeRegistryLookup:
    """Verify that _register_agent_runtime_bridge prefers registered defs."""

    async def test_bridge_uses_registered_definition(self) -> None:
        """When the agent name is in the registry, use its definition."""
        from agent33.agents.registry import AgentRegistry

        registry = AgentRegistry()
        registered_def = _make_definition(
            name="code-worker",
            governance=GovernanceConstraints(scope="workspace", commands="test,lint"),
        )
        registry.register(registered_def)

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "built"}',
                model="test-model",
                prompt_tokens=30,
                completion_tokens=30,
            )
        )

        captured_bridge = {}

        def fake_register(name: str, handler: object) -> None:
            captured_bridge[name] = handler

        from agent33.main import _register_agent_runtime_bridge

        _register_agent_runtime_bridge(mock_router, fake_register, registry=registry)

        bridge_fn = captured_bridge["__default__"]
        await bridge_fn({"agent_name": "code-worker", "task": "build it"})

        # Should have called the LLM
        assert mock_router.complete.called
        # Verify the system prompt includes governance from the registered def
        messages = mock_router.complete.call_args[0][0]
        system_msg = messages[0].content
        assert "# Governance Constraints" in system_msg
        assert "workspace" in system_msg

    async def test_bridge_falls_back_for_unknown_agent(self) -> None:
        """When agent is not in the registry, fall back to throwaway def."""
        from agent33.agents.registry import AgentRegistry

        registry = AgentRegistry()  # empty

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "ok"}',
                model="test-model",
                prompt_tokens=20,
                completion_tokens=20,
            )
        )

        captured_bridge = {}

        def fake_register(name: str, handler: object) -> None:
            captured_bridge[name] = handler

        from agent33.main import _register_agent_runtime_bridge

        _register_agent_runtime_bridge(mock_router, fake_register, registry=registry)

        bridge_fn = captured_bridge["__default__"]
        result = await bridge_fn({"agent_name": "unknown-agent", "task": "hello"})

        # Should still work with the fallback definition
        assert result == {"result": "ok"}
        # The system prompt should have safety rules even for throwaway defs
        messages = mock_router.complete.call_args[0][0]
        system_msg = messages[0].content
        assert "# Safety Rules" in system_msg

    async def test_bridge_works_without_registry(self) -> None:
        """When registry is None, always use throwaway definition."""
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "fallback"}',
                model="test-model",
                prompt_tokens=10,
                completion_tokens=10,
            )
        )

        captured_bridge = {}

        def fake_register(name: str, handler: object) -> None:
            captured_bridge[name] = handler

        from agent33.main import _register_agent_runtime_bridge

        _register_agent_runtime_bridge(mock_router, fake_register, registry=None)

        bridge_fn = captured_bridge["__default__"]
        result = await bridge_fn({"agent_name": "any-agent", "task": "go"})
        assert result == {"result": "fallback"}

    async def test_bridge_passes_explicit_active_skills_to_runtime_prompt(self) -> None:
        """Workflow bridge should allow templates to activate imported skills."""
        from agent33.agents.registry import AgentRegistry
        from agent33.skills.definition import SkillDefinition
        from agent33.skills.injection import SkillInjector
        from agent33.skills.registry import SkillRegistry

        registry = AgentRegistry()
        registry.register(_make_definition(name="code-worker"))

        skill_registry = SkillRegistry()
        skill_registry.register(
            SkillDefinition(
                name="workflow-ops/pr-manager",
                description="PR review automation",
                instructions="Use the PR manager workflow.",
            )
        )

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(
            return_value=LLMResponse(
                content='{"result": "ok"}',
                model="test-model",
                prompt_tokens=20,
                completion_tokens=20,
            )
        )

        captured_bridge = {}

        def fake_register(name: str, handler: object) -> None:
            captured_bridge[name] = handler

        from agent33.main import _register_agent_runtime_bridge

        _register_agent_runtime_bridge(
            mock_router,
            fake_register,
            registry=registry,
            skill_injector=SkillInjector(skill_registry),
        )

        bridge_fn = captured_bridge["__default__"]
        await bridge_fn(
            {
                "agent_name": "code-worker",
                "task": "review the PR",
                "active_skills": ["workflow-ops/pr-manager"],
            }
        )

        messages = mock_router.complete.call_args[0][0]
        system_msg = messages[0].content
        assert "# Active Skill: workflow-ops/pr-manager" in system_msg
        assert "Use the PR manager workflow." in system_msg
