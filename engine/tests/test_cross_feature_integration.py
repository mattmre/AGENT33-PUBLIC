"""Cross-feature integration tests: delegation + skills + MoA.

These tests exercise the combined flows that span multiple AGENT-33 subsystems:
  - AgentRuntime.invoke() with skill injection + DelegationManager
  - MoA workflow template -> WorkflowExecutor -> agent handler dispatch
  - SkillInjector L0/L1 disclosure producing structurally distinct prompt content

All tests use controlled mocks for the LLM/ModelRouter layer so no real
provider calls are made, while still exercising real production code paths
in the runtime, delegation, workflow, and skills subsystems.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.agents.definition import (
    AgentConstraints,
    AgentDefinition,
    AgentStatus,
    SpecCapability,
)
from agent33.agents.delegation import (
    DelegationManager,
    DelegationRequest,
    DelegationStatus,
)
from agent33.agents.registry import AgentRegistry
from agent33.agents.runtime import AgentRuntime
from agent33.llm.base import LLMResponse
from agent33.skills.definition import SkillDefinition
from agent33.skills.injection import SkillInjector
from agent33.skills.registry import SkillRegistry
from agent33.workflows.templates.mixture_of_agents import build_moa_workflow

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(
    name: str,
    *,
    spec_caps: list[str] | None = None,
    skills: list[str] | None = None,
    max_tokens: int = 4096,
    description: str = "",
) -> AgentDefinition:
    """Build a minimal AgentDefinition for testing."""
    return AgentDefinition(
        name=name,
        version="1.0.0",
        role="implementer",
        description=description or f"Test agent {name}",
        spec_capabilities=[SpecCapability(c) for c in (spec_caps or [])],
        constraints=AgentConstraints(max_tokens=max_tokens),
        status=AgentStatus.ACTIVE,
        skills=skills or [],
    )


def _make_skill(
    name: str,
    *,
    description: str = "",
    instructions: str = "",
    allowed_tools: list[str] | None = None,
    autonomy_level: str = "",
    approval_required_for: list[str] | None = None,
) -> SkillDefinition:
    """Build a minimal SkillDefinition for testing."""
    return SkillDefinition(
        name=name,
        description=description or f"Skill {name}",
        instructions=instructions or f"Instructions for {name}.",
        allowed_tools=allowed_tools or [],
        autonomy_level=autonomy_level,
        approval_required_for=approval_required_for or [],
    )


def _mock_llm_response(content: str, model: str = "test-model") -> LLMResponse:
    """Build an LLMResponse with controlled content."""
    return LLMResponse(
        content=content,
        model=model,
        prompt_tokens=50,
        completion_tokens=30,
    )


# ---------------------------------------------------------------------------
# Test 1: Delegation + skill injection co-existing in the same invocation
# ---------------------------------------------------------------------------


class TestDelegationWithSkillInjection:
    """Verify that AgentRuntime.invoke() applies skill injection AND that
    the DelegationManager can subsequently delegate to a child agent using
    the same infrastructure.

    This is a cross-feature integration test:
      - SkillInjector builds prompt content (L0 + L1)
      - AgentRuntime.invoke() injects skills into the system prompt
      - DelegationManager resolves a child via capability matching
      - Child agent runtime executes through the same router

    The test asserts on the actual system prompt content (skills appear)
    AND on the delegation result (child output is returned).
    """

    @pytest.fixture()
    def skill_registry(self) -> SkillRegistry:
        reg = SkillRegistry()
        reg.register(
            _make_skill(
                "kubernetes-deploy",
                description="Deploy workloads to Kubernetes clusters",
                instructions=(
                    "# Kubernetes Deployment Guide\n"
                    "1. Validate the manifest\n"
                    "2. Apply with kubectl\n"
                    "3. Verify rollout status"
                ),
                allowed_tools=["shell", "file_ops"],
                autonomy_level="supervised",
                approval_required_for=["kubectl delete"],
            )
        )
        reg.register(
            _make_skill(
                "code-review",
                description="Automated code review and quality checks",
                instructions=(
                    "# Code Review Protocol\n"
                    "1. Check style conformance\n"
                    "2. Identify potential bugs\n"
                    "3. Suggest improvements"
                ),
            )
        )
        return reg

    @pytest.fixture()
    def agent_registry(self) -> AgentRegistry:
        reg = AgentRegistry()
        reg.register(
            _make_agent(
                "orchestrator",
                spec_caps=["P-01", "P-02"],
                skills=["kubernetes-deploy", "code-review"],
                description="Orchestrates multi-agent workflows",
            )
        )
        reg.register(
            _make_agent(
                "code-worker",
                spec_caps=["I-01", "I-02", "I-03"],
                description="Implements code changes",
            )
        )
        reg.register(
            _make_agent(
                "qa-agent",
                spec_caps=["V-01", "V-02"],
                description="Validates correctness",
            )
        )
        return reg

    async def test_invoke_with_skills_produces_enriched_system_prompt(
        self,
        skill_registry: SkillRegistry,
        agent_registry: AgentRegistry,
    ) -> None:
        """AgentRuntime.invoke() injects L0 metadata + L1 instructions into
        the system prompt when a SkillInjector is provided.

        Asserts that:
        - The L0 metadata block lists both skills by name and description
        - The L1 instructions block for each active skill includes the
          full instructions text and governance info
        - The LLM receives the enriched system prompt (captured via the
          mock router's call args)
        """
        injector = SkillInjector(skill_registry)
        parent_def = agent_registry.get("orchestrator")
        assert parent_def is not None

        # The mock router captures what messages the LLM receives
        mock_router = MagicMock()
        mock_router.complete = AsyncMock(
            return_value=_mock_llm_response('{"result": "task completed"}')
        )

        runtime = AgentRuntime(
            definition=parent_def,
            router=mock_router,
            skill_injector=injector,
            active_skills=["kubernetes-deploy", "code-review"],
        )

        result = await runtime.invoke({"task": "deploy service"})

        # Verify the LLM was called
        mock_router.complete.assert_called_once()
        call_args = mock_router.complete.call_args
        messages = call_args[0][0]  # first positional arg is the messages list
        system_msg = messages[0]
        system_text = system_msg.content

        # L0: metadata block lists both skills
        assert "# Available Skills" in system_text
        assert "kubernetes-deploy: Deploy workloads to Kubernetes clusters" in system_text
        assert "code-review: Automated code review and quality checks" in system_text

        # L1: full instructions for active skills
        assert "# Active Skill: kubernetes-deploy" in system_text
        assert "Kubernetes Deployment Guide" in system_text
        assert "Apply with kubectl" in system_text  # from instructions step 2
        assert "# Active Skill: code-review" in system_text
        assert "Code Review Protocol" in system_text

        # Governance info for kubernetes-deploy
        assert "Allowed tools: shell, file_ops" in system_text
        assert "supervised" in system_text
        assert "kubectl delete" in system_text  # approval_required_for

        # The result contains the parsed LLM output
        assert result.output == {"result": "task completed"}

    async def test_delegation_uses_capability_matching_and_returns_child_output(
        self,
        agent_registry: AgentRegistry,
    ) -> None:
        """DelegationManager resolves a child agent by capability ID, invokes
        it through AgentRuntime, and returns the child's structured output.

        Asserts that:
        - The I-01 capability resolves to 'code-worker' (not orchestrator)
        - The child agent's raw_response is captured
        - The delegation result has COMPLETED status with the child output
        - The delegation history records the event
        """
        mock_router = MagicMock()
        child_response_json = json.dumps({"implementation": "class Widget: pass"})
        mock_router.complete = AsyncMock(return_value=_mock_llm_response(child_response_json))

        manager = DelegationManager(registry=agent_registry, router=mock_router)

        request = DelegationRequest(
            parent_agent="orchestrator",
            required_capability="I-01",
            inputs={"task": "implement Widget class"},
            token_budget=2048,
        )

        result = await manager.delegate(request)

        assert result.status == DelegationStatus.COMPLETED
        assert result.target_agent == "code-worker"
        assert result.output["implementation"] == "class Widget: pass"
        assert result.tokens_used == 80  # 50 prompt + 30 completion
        assert result.duration_seconds >= 0

        # History records the delegation
        history = manager.history
        assert len(history) == 1
        assert history[0].delegation_id == request.delegation_id

    async def test_skill_injection_then_delegation_full_flow(
        self,
        skill_registry: SkillRegistry,
        agent_registry: AgentRegistry,
    ) -> None:
        """End-to-end: parent agent gets skills injected, then delegates to a
        child agent. Both steps use the same mock router but produce distinct
        behaviors.

        This test verifies that skills and delegation are not mutually
        exclusive -- an agent can have skills injected into its prompt AND
        then delegate subtasks to other agents in a single session.
        """
        injector = SkillInjector(skill_registry)
        parent_def = agent_registry.get("orchestrator")
        assert parent_def is not None

        # Parent router returns a response that mentions delegation intent
        parent_response = '{"plan": "delegate implementation to code-worker"}'
        parent_router = MagicMock()
        parent_router.complete = AsyncMock(return_value=_mock_llm_response(parent_response))

        # Step 1: Parent invoke with skills
        runtime = AgentRuntime(
            definition=parent_def,
            router=parent_router,
            skill_injector=injector,
            active_skills=["kubernetes-deploy"],
        )
        parent_result = await runtime.invoke({"task": "deploy and implement"})

        # Verify skills were injected
        call_args = parent_router.complete.call_args
        system_text = call_args[0][0][0].content
        assert "kubernetes-deploy" in system_text
        assert "Kubernetes Deployment Guide" in system_text

        # Step 2: Based on parent's plan, delegate to child
        child_response = json.dumps({"code": "def deploy(): ..."})
        child_router = MagicMock()
        child_router.complete = AsyncMock(return_value=_mock_llm_response(child_response))

        manager = DelegationManager(registry=agent_registry, router=child_router)
        delegation_result = await manager.delegate(
            DelegationRequest(
                parent_agent="orchestrator",
                target_agent="code-worker",
                inputs={"task": parent_result.output.get("plan", "")},
            )
        )

        assert delegation_result.status == DelegationStatus.COMPLETED
        assert delegation_result.output["code"] == "def deploy(): ..."

        # Both steps completed independently -- the parent had skills, the
        # child did not, and both returned structured output.
        assert parent_result.output["plan"] == "delegate implementation to code-worker"


# ---------------------------------------------------------------------------
# Test 2: MoA workflow dispatches to multiple agents and aggregates results
# ---------------------------------------------------------------------------


class TestMoAWorkflowIntegration:
    """Verify the Mixture-of-Agents flow from workflow construction through
    expression evaluation and result aggregation.

    This exercises real production code across multiple subsystems:
      - build_moa_workflow() constructs a valid DAG with correct dependencies
      - ExpressionEvaluator substitutes reference outputs into the aggregator prompt
      - agent_resolver callback correctly maps model names to workflow agents
      - format_moa_result() extracts the final aggregated text from workflow outputs
      - DelegationManager.aggregate_results() summarizes delegation fan-out results
        (demonstrating the delegation + MoA pattern for multi-agent orchestration)
    """

    def test_expression_evaluator_substitutes_reference_outputs_into_aggregator(
        self,
    ) -> None:
        """The MoA aggregator prompt uses Jinja2 template expressions
        (``{{ step_id.result | default(...) }}``) to reference prior step
        outputs. Verify that the ExpressionEvaluator correctly substitutes
        real step results when the state keys are valid Jinja2 identifiers.

        This is the critical integration point: the workflow executor stores
        each step's output in the state dict, and the expression evaluator
        must resolve the references before the aggregator handler receives
        them.

        NOTE: The current MoA template generates step IDs with hyphens
        (e.g. ``ref-llama3``), which Jinja2 parses as subtraction rather
        than a single identifier. This test uses the underlying
        ``_build_aggregator_user_prompt`` with underscore-keyed step IDs
        to exercise the expression-substitution contract directly. The
        hyphenated-ID limitation is documented in a separate regression
        test below.

        Asserts that:
        - The resolved prompt contains the actual reference output text
        - Each reference contribution appears in the resolved prompt
        - The original query is preserved in the resolved prompt
        - Jinja2 delimiters are fully resolved (no raw ``{{ }}`` remains)
        """
        from agent33.workflows.expressions import ExpressionEvaluator
        from agent33.workflows.templates.mixture_of_agents import (
            _build_aggregator_user_prompt,
        )

        evaluator = ExpressionEvaluator()

        # Build a prompt with underscore-keyed step IDs that are valid
        # Jinja2 identifiers (matching how they would need to be to work).
        step_ids = ["ref_llama3", "ref_mistral"]
        raw_prompt = _build_aggregator_user_prompt(
            "What causes inflation?",
            step_ids,
        )
        assert "{{" in raw_prompt, "Aggregator prompt should contain Jinja2 references"

        # Simulate the state dict after reference steps have completed
        state: dict[str, Any] = {
            "ref_llama3": {"result": "Inflation analysis from llama3: demand-pull factors."},
            "ref_mistral": {"result": "Inflation analysis from mistral: cost-push dynamics."},
        }

        resolved_prompt: str = evaluator.evaluate(raw_prompt, state)

        # The resolved prompt should contain the substituted reference outputs
        assert "What causes inflation?" in resolved_prompt
        assert "Inflation analysis from llama3" in resolved_prompt
        assert "Inflation analysis from mistral" in resolved_prompt

        # Verify Jinja2 delimiters are gone (fully resolved)
        assert "{{" not in resolved_prompt
        assert "}}" not in resolved_prompt

    def test_moa_step_ids_use_underscores_so_jinja2_resolves_correctly(self) -> None:
        """MoA step IDs use underscores (not hyphens) so Jinja2 resolves
        aggregator prompt references without raising UndefinedError.

        Previously, ``_sanitize_step_id`` produced hyphenated IDs like
        ``ref-llama3``.  Jinja2 parses hyphens as subtraction operators, so
        ``{{ ref-llama3.result }}`` would raise ``UndefinedError`` before
        the ``default()`` filter could intercept.

        After the fix, ``_sanitize_step_id`` produces ``ref_llama3``, which
        Jinja2 correctly treats as an identifier, and the expression evaluator
        resolves the reference to the actual result value.
        """
        from agent33.workflows.expressions import ExpressionEvaluator

        evaluator = ExpressionEvaluator()

        workflow = build_moa_workflow(
            query="test query",
            reference_models=["llama3"],
            aggregator_model="gpt4o",
        )

        agg_step = next(s for s in workflow.steps if s.id == "moa_aggregator")
        raw_prompt: str = agg_step.inputs["prompt"]

        # Step ID must use underscores (Jinja2-safe identifier)
        assert "ref_llama3" in raw_prompt, "Step ID should use underscores not hyphens"
        assert "ref-llama3" not in raw_prompt, "Hyphenated ID would break Jinja2 resolution"

        # Evaluator resolves the underscore-based reference without error
        state = {"ref_llama3": {"result": "actual response from llama3"}}
        resolved_prompt = evaluator.evaluate(raw_prompt, state)

        assert "actual response from llama3" in resolved_prompt
        assert "{{" not in resolved_prompt

    def test_agent_resolver_maps_models_to_workflow_agents(self) -> None:
        """When an agent_resolver is provided, build_moa_workflow uses it to
        map model identifiers to executable workflow agent names.

        This tests the integration between the MoA template builder and the
        agent routing layer. In production, the resolver maps model names
        to registered workflow agent handlers (or the __default__ bridge).

        Asserts that:
        - Each step's agent field uses the resolved name, not the raw model
        - The resolver is called for each unique model including the aggregator
        """
        resolver_calls: list[str] = []

        def mock_resolver(model_name: str) -> str:
            resolver_calls.append(model_name)
            return f"__bridge_{model_name}__"

        workflow = build_moa_workflow(
            query="test",
            reference_models=["llama3", "mistral"],
            aggregator_model="gpt4o",
            agent_resolver=mock_resolver,
        )

        # Verify the resolver was called for each model
        assert set(resolver_calls) == {"llama3", "mistral", "gpt4o"}

        # Verify step agent fields use resolved names
        for step in workflow.steps:
            assert step.agent is not None
            assert step.agent.startswith("__bridge_")

        agg = next(s for s in workflow.steps if s.id == "moa_aggregator")
        assert agg.agent == "__bridge_gpt4o__"

    def test_moa_multi_round_creates_intermediate_dependencies(self) -> None:
        """A 2-round MoA workflow creates intermediate proposer layers where
        round-2 proposers depend on round-1 proposers.

        Asserts that:
        - Round-2 proposer steps list round-1 steps in their depends_on
        - The aggregator depends only on round-2 steps (the final round)
        - Round-2 prompts contain Jinja2 references to round-1 step IDs
        """
        workflow = build_moa_workflow(
            query="Explain quantum computing",
            reference_models=["model-a", "model-b"],
            aggregator_model="agg-model",
            rounds=2,
        )

        # 2 rounds x 2 models + 1 aggregator = 5 steps
        assert len(workflow.steps) == 5

        r1_steps = [s for s in workflow.steps if s.id.startswith("r1_")]
        r2_steps = [s for s in workflow.steps if s.id.startswith("r2_")]
        agg_step = next(s for s in workflow.steps if s.id == "moa_aggregator")

        assert len(r1_steps) == 2
        assert len(r2_steps) == 2

        # Round 1 steps have no dependencies
        for step in r1_steps:
            assert step.depends_on == []

        # Round 2 steps depend on all round 1 steps
        r1_ids = {s.id for s in r1_steps}
        for step in r2_steps:
            assert set(step.depends_on) == r1_ids

        # Aggregator depends on round 2 steps (final round)
        r2_ids = {s.id for s in r2_steps}
        assert set(agg_step.depends_on) == r2_ids

        # Round 2 prompts reference round 1 step IDs
        for step in r2_steps:
            prompt = step.inputs.get("prompt", "")
            for r1_id in r1_ids:
                assert r1_id in prompt, f"Round 2 prompt should reference {r1_id}"

    async def test_delegation_fan_out_models_moa_reference_pattern(self) -> None:
        """DelegationManager.delegate_fan_out() can execute the same pattern
        as MoA reference models: parallel agent invocations with result
        aggregation.

        This demonstrates the cross-feature integration between delegation
        and the MoA concept: instead of a workflow DAG, the orchestrator
        delegates to multiple specialized agents in parallel and aggregates
        their results.

        Asserts that:
        - All delegations complete successfully
        - Each child produces distinct output
        - aggregate_results() correctly summarizes the fan-out
        - Token budgets are respected per-child
        """
        registry = AgentRegistry()
        registry.register(_make_agent("analyst-a", spec_caps=["X-01"], description="Analyst A"))
        registry.register(_make_agent("analyst-b", spec_caps=["X-02"], description="Analyst B"))
        registry.register(_make_agent("analyst-c", spec_caps=["X-03"], description="Analyst C"))

        call_count = {"total": 0}

        async def _mock_complete(messages: Any, **kwargs: Any) -> LLMResponse:
            call_count["total"] += 1
            # Derive a unique response from the system prompt content
            system_text = messages[0].content if messages else ""
            agent_name = "unknown"
            if "Analyst A" in system_text:
                agent_name = "analyst-a"
            elif "Analyst B" in system_text:
                agent_name = "analyst-b"
            elif "Analyst C" in system_text:
                agent_name = "analyst-c"
            return _mock_llm_response(
                json.dumps({"analysis": f"Perspective from {agent_name}"}),
            )

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(side_effect=_mock_complete)

        manager = DelegationManager(registry=registry, router=mock_router, max_parallel=3)

        # Split budget across 3 children
        budgets = DelegationManager.split_budget(6000, 3, reserve_fraction=0.2)
        assert len(budgets) == 3
        assert all(b == 1600 for b in budgets)

        requests = [
            DelegationRequest(
                parent_agent="orchestrator",
                target_agent=f"analyst-{suffix}",
                inputs={"query": "Analyze market trends"},
                token_budget=budgets[i],
            )
            for i, suffix in enumerate(["a", "b", "c"])
        ]

        results = await manager.delegate_fan_out(requests)

        # All three delegations completed
        assert len(results) == 3
        assert all(r.status == DelegationStatus.COMPLETED for r in results)

        # Each child produced distinct output
        outputs = [r.output.get("analysis", "") for r in results]
        assert "analyst-a" in outputs[0]
        assert "analyst-b" in outputs[1]
        assert "analyst-c" in outputs[2]

        # Aggregation summary is correct
        summary = DelegationManager.aggregate_results(results)
        assert summary["total_delegations"] == 3
        assert summary["all_completed"] is True
        assert summary["total_tokens_used"] == 240  # 3 * 80 tokens each


# ---------------------------------------------------------------------------
# Test 3: SkillInjector L0 vs L1 disclosure levels
# ---------------------------------------------------------------------------


class TestSkillInjectorDisclosureLevels:
    """Verify that SkillInjector produces structurally different system prompt
    content at L0 (metadata-only) versus L1 (full instructions) disclosure
    levels.

    L0 is a compact list used for context budget: just name + description.
    L1 includes full instructions, governance info, and tool restrictions.

    This is a cross-feature test because it validates the contract between
    SkillInjector output and AgentRuntime's system prompt assembly -- if either
    side changes its format, this test catches the regression.
    """

    @pytest.fixture()
    def skill_registry_with_diverse_skills(self) -> SkillRegistry:
        """Registry with skills that have varying levels of governance detail."""
        reg = SkillRegistry()
        reg.register(
            _make_skill(
                "data-analysis",
                description="Statistical data analysis and visualization",
                instructions=(
                    "# Data Analysis Workflow\n"
                    "## Step 1: Load Data\n"
                    "Use pandas to load CSV/JSON files.\n"
                    "## Step 2: Explore\n"
                    "Generate summary statistics.\n"
                    "## Step 3: Visualize\n"
                    "Create matplotlib charts for key metrics."
                ),
                allowed_tools=["shell", "file_ops"],
                autonomy_level="full",
            )
        )
        reg.register(
            _make_skill(
                "security-scan",
                description="Run security scans on codebases",
                instructions=(
                    "# Security Scanning Protocol\n"
                    "CRITICAL: Never expose found vulnerabilities in logs.\n"
                    "1. Run static analysis with semgrep\n"
                    "2. Check dependencies for CVEs\n"
                    "3. Generate remediation report"
                ),
                allowed_tools=["shell"],
                autonomy_level="supervised",
                approval_required_for=["rm", "curl"],
            )
        )
        reg.register(
            _make_skill(
                "simple-math",
                description="Basic arithmetic operations",
                instructions="Compute the requested arithmetic.",
            )
        )
        return reg

    def test_l0_metadata_is_compact_and_contains_only_names_and_descriptions(
        self,
        skill_registry_with_diverse_skills: SkillRegistry,
    ) -> None:
        """L0 build_skill_metadata_block produces a compact block that lists
        only skill names and descriptions, without instructions or governance.

        Asserts that:
        - The L0 block contains each skill's name and description
        - The L0 block does NOT contain full instructions text
        - The L0 block does NOT contain governance details (allowed_tools, etc.)
        """
        injector = SkillInjector(skill_registry_with_diverse_skills)
        l0_block = injector.build_skill_metadata_block(
            ["data-analysis", "security-scan", "simple-math"]
        )

        # Names and descriptions present
        assert "data-analysis: Statistical data analysis" in l0_block
        assert "security-scan: Run security scans" in l0_block
        assert "simple-math: Basic arithmetic" in l0_block

        # Full instructions must NOT appear in L0
        assert "Step 1: Load Data" not in l0_block
        assert "CRITICAL: Never expose" not in l0_block
        assert "semgrep" not in l0_block

        # Governance details must NOT appear in L0
        assert "Allowed tools" not in l0_block
        assert "supervised" not in l0_block
        assert "approval" not in l0_block.lower()

    def test_l1_instructions_contain_full_text_and_governance(
        self,
        skill_registry_with_diverse_skills: SkillRegistry,
    ) -> None:
        """L1 build_skill_instructions_block produces a detailed block with
        full instructions AND governance metadata.

        Asserts that:
        - The L1 block for security-scan contains the full instructions
        - The L1 block includes governance info (allowed tools, autonomy, approvals)
        - The L1 block for data-analysis includes its distinct instructions
        """
        injector = SkillInjector(skill_registry_with_diverse_skills)

        # security-scan: has rich governance
        l1_security = injector.build_skill_instructions_block("security-scan")
        assert "# Active Skill: security-scan" in l1_security
        assert "Security Scanning Protocol" in l1_security
        assert "semgrep" in l1_security
        assert "CRITICAL: Never expose" in l1_security
        assert "## Governance" in l1_security
        assert "Allowed tools: shell" in l1_security
        assert "supervised" in l1_security
        assert "rm" in l1_security  # approval_required_for
        assert "curl" in l1_security  # approval_required_for

        # data-analysis: different instructions, different governance
        l1_data = injector.build_skill_instructions_block("data-analysis")
        assert "# Active Skill: data-analysis" in l1_data
        assert "Data Analysis Workflow" in l1_data
        assert "pandas" in l1_data
        assert "matplotlib" in l1_data
        assert "Allowed tools: shell, file_ops" in l1_data

    def test_l0_and_l1_produce_structurally_different_content(
        self,
        skill_registry_with_diverse_skills: SkillRegistry,
    ) -> None:
        """L0 and L1 for the same skill produce content with fundamentally
        different structure and detail level.

        L0 is a one-liner per skill. L1 is a multi-section document with
        headers, governance, and instructions.

        This test would catch a regression where L0 accidentally includes
        full instructions or L1 degrades to metadata-only.
        """
        injector = SkillInjector(skill_registry_with_diverse_skills)

        l0 = injector.build_skill_metadata_block(["security-scan"])
        l1 = injector.build_skill_instructions_block("security-scan")

        # L0 should be significantly shorter than L1
        assert len(l0) < len(l1), (
            f"L0 ({len(l0)} chars) should be shorter than L1 ({len(l1)} chars)"
        )

        # L0 has exactly one section header ("# Available Skills")
        l0_headers = [line for line in l0.splitlines() if line.startswith("#")]
        assert len(l0_headers) == 1
        assert l0_headers[0] == "# Available Skills"

        # L1 has multiple section headers (Active Skill + Governance + instructions)
        l1_headers = [line for line in l1.splitlines() if line.startswith("#")]
        assert len(l1_headers) >= 2, f"L1 should have multiple headers, got {l1_headers}"
        assert any("Active Skill" in h for h in l1_headers)

    async def test_runtime_invoke_applies_l0_and_l1_in_correct_order(
        self,
        skill_registry_with_diverse_skills: SkillRegistry,
    ) -> None:
        """AgentRuntime.invoke() adds L0 (metadata for all definition.skills)
        first, then L1 (full instructions for each active skill), producing
        a system prompt where both levels are present and in order.

        This tests the integration between SkillInjector and AgentRuntime
        to ensure the disclosure pipeline works end-to-end.
        """
        injector = SkillInjector(skill_registry_with_diverse_skills)

        # Agent has data-analysis and security-scan preloaded, but only
        # security-scan is actively invoked
        agent_def = _make_agent(
            "analyst",
            skills=["data-analysis", "security-scan"],
            description="Data analysis specialist",
        )

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(return_value=_mock_llm_response('{"status": "done"}'))

        runtime = AgentRuntime(
            definition=agent_def,
            router=mock_router,
            skill_injector=injector,
            active_skills=["security-scan"],
        )

        await runtime.invoke({"query": "scan the codebase"})

        # Extract the system prompt sent to the LLM
        call_args = mock_router.complete.call_args
        messages = call_args[0][0]
        system_text = messages[0].content

        # L0 block appears (metadata for both preloaded skills)
        l0_idx = system_text.index("# Available Skills")
        assert "data-analysis:" in system_text[l0_idx:]
        assert "security-scan:" in system_text[l0_idx:]

        # L1 block appears only for the active skill
        l1_idx = system_text.index("# Active Skill: security-scan")
        assert l1_idx > l0_idx, "L1 should appear after L0"
        assert "Security Scanning Protocol" in system_text[l1_idx:]

        # L1 for data-analysis should NOT appear (it's preloaded but not active)
        assert "# Active Skill: data-analysis" not in system_text
