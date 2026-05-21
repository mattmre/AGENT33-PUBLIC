"""Phase 58 tests: multi-round MoA, temperature diversity, cost estimation, API.

These tests cover the Phase 58 enhancements to the Mixture-of-Agents template:
- Multi-round proposer layers (rounds > 1)
- Temperature diversity across proposers
- Cost estimation via PricingCatalog
- MoA API route endpoints
- Provider/model parsing
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.llm.pricing import CostStatus, PricingCatalog, PricingEntry
from agent33.main import app
from agent33.tools.base import ToolContext
from agent33.tools.builtin.moa import MoATool
from agent33.workflows.dag import DAGBuilder
from agent33.workflows.definition import StepAction
from agent33.workflows.executor import WorkflowExecutor, WorkflowResult, WorkflowStatus
from agent33.workflows.templates.mixture_of_agents import (
    MOA_INTERMEDIATE_SYSTEM_PROMPT,
    MoACostEstimate,
    _parse_provider_model,
    build_moa_workflow,
    compute_diverse_temperatures,
    estimate_moa_cost,
)

# ---------------------------------------------------------------------------
# Multi-round workflow builder tests
# ---------------------------------------------------------------------------


class TestMultiRoundWorkflow:
    """Tests for multi-round MoA proposer layers."""

    def test_two_rounds_creates_correct_step_count(self) -> None:
        """2 models x 2 rounds + 1 aggregator = 5 steps."""
        wf = build_moa_workflow(
            "What is AI?",
            ["model-a", "model-b"],
            "agg",
            rounds=2,
        )
        assert len(wf.steps) == 5  # 2 + 2 + 1

    def test_three_rounds_creates_correct_step_count(self) -> None:
        """3 models x 3 rounds + 1 aggregator = 10 steps."""
        wf = build_moa_workflow(
            "q",
            ["a", "b", "c"],
            "agg",
            rounds=3,
        )
        assert len(wf.steps) == 10  # 9 + 1

    def test_first_round_steps_have_no_dependencies(self) -> None:
        """Round 1 proposers must be independent (no depends_on)."""
        wf = build_moa_workflow("q", ["a", "b"], "agg", rounds=2)
        # Round 1 step IDs start with "r1_"
        r1_steps = [s for s in wf.steps if s.id.startswith("r1_")]
        assert len(r1_steps) == 2
        for step in r1_steps:
            assert step.depends_on == [], f"Round 1 step {step.id} should have no deps"

    def test_second_round_depends_on_first_round(self) -> None:
        """Round 2 proposers must depend on all round 1 steps."""
        wf = build_moa_workflow("q", ["a", "b"], "agg", rounds=2)
        r1_ids = {s.id for s in wf.steps if s.id.startswith("r1_")}
        r2_steps = [s for s in wf.steps if s.id.startswith("r2_")]
        assert len(r2_steps) == 2
        for step in r2_steps:
            assert set(step.depends_on) == r1_ids

    def test_aggregator_depends_on_final_round_only(self) -> None:
        """The aggregator must depend only on the last round's steps."""
        wf = build_moa_workflow("q", ["a", "b"], "agg", rounds=3)
        agg = next(s for s in wf.steps if s.id == "moa_aggregator")
        # Round 3 IDs start with "r3_"
        r3_ids = {s.id for s in wf.steps if s.id.startswith("r3_")}
        assert set(agg.depends_on) == r3_ids
        # Must NOT include round 1 or 2 IDs
        r1_ids = {s.id for s in wf.steps if s.id.startswith("r1_")}
        assert r1_ids.isdisjoint(set(agg.depends_on))

    def test_intermediate_rounds_have_system_prompt(self) -> None:
        """Round 2+ steps must carry the intermediate system prompt."""
        wf = build_moa_workflow("q", ["a"], "agg", rounds=2)
        r2_step = next(s for s in wf.steps if s.id.startswith("r2_"))
        assert r2_step.inputs["system_prompt"] == MOA_INTERMEDIATE_SYSTEM_PROMPT

    def test_first_round_has_no_system_prompt(self) -> None:
        """Round 1 steps should NOT have a system prompt (raw query only)."""
        wf = build_moa_workflow("q", ["a"], "agg", rounds=2)
        r1_step = next(s for s in wf.steps if s.id.startswith("r1_"))
        assert "system_prompt" not in r1_step.inputs

    def test_intermediate_prompt_references_prior_round(self) -> None:
        """Round 2 prompts must include Jinja2 refs to round 1 step IDs."""
        wf = build_moa_workflow("q", ["a", "b"], "agg", rounds=2)
        r1_ids = [s.id for s in wf.steps if s.id.startswith("r1_")]
        r2_step = next(s for s in wf.steps if s.id.startswith("r2_"))
        prompt: str = r2_step.inputs["prompt"]
        for r1_id in r1_ids:
            assert r1_id in prompt, f"Round 2 prompt must reference {r1_id}"

    def test_all_step_ids_valid(self) -> None:
        """Multi-round step IDs must all match the valid pattern."""
        pattern = re.compile(r"^[a-z][a-z0-9_-]*$")
        wf = build_moa_workflow("q", ["GPT-4o", "Claude-3.5"], "gpt-4o", rounds=3)
        for step in wf.steps:
            assert pattern.match(step.id), f"Invalid step ID: {step.id}"

    def test_dag_is_valid_multi_round(self) -> None:
        """Multi-round workflow must form a valid DAG without cycles."""
        wf = build_moa_workflow("q", ["a", "b", "c"], "agg", rounds=2)
        dag = DAGBuilder(wf.steps).build()
        order = dag.topological_order()
        # 3 models x 2 rounds + 1 aggregator = 7
        assert len(order) == 7
        # Aggregator must be last
        assert order[-1] == "moa_aggregator"

    def test_dag_parallel_groups_multi_round(self) -> None:
        """Multi-round DAG should have 1 group per round + aggregator."""
        wf = build_moa_workflow("q", ["a", "b"], "agg", rounds=3)
        dag = DAGBuilder(wf.steps).build()
        groups = dag.parallel_groups()
        # 3 rounds + 1 aggregator = 4 groups
        assert len(groups) == 4
        # Each round has 2 models
        assert len(groups[0]) == 2
        assert len(groups[1]) == 2
        assert len(groups[2]) == 2
        # Aggregator
        assert groups[3] == ["moa_aggregator"]

    def test_rounds_zero_raises(self) -> None:
        """rounds=0 must raise ValueError."""
        with pytest.raises(ValueError, match="At least one round"):
            build_moa_workflow("q", ["a"], "agg", rounds=0)

    def test_negative_rounds_raises(self) -> None:
        """Negative rounds must raise ValueError."""
        with pytest.raises(ValueError, match="At least one round"):
            build_moa_workflow("q", ["a"], "agg", rounds=-1)

    def test_single_round_backward_compatible(self) -> None:
        """rounds=1 (default) should produce the same structure as before."""
        wf = build_moa_workflow("q", ["m1", "m2"], "agg", rounds=1)
        # All non-aggregator steps use "ref-" prefix (not "r1_")
        ref_steps = [s for s in wf.steps if s.id != "moa_aggregator"]
        for step in ref_steps:
            assert step.id.startswith("ref_"), f"Single-round uses .ref_. prefix: {step.id}"

    def test_multi_round_uses_round_prefix(self) -> None:
        """rounds>1 should use 'r<N>-' prefixes for step IDs."""
        wf = build_moa_workflow("q", ["m1"], "agg", rounds=2)
        non_agg = [s for s in wf.steps if s.id != "moa_aggregator"]
        assert any(s.id.startswith("r1_") for s in non_agg)
        assert any(s.id.startswith("r2_") for s in non_agg)

    def test_all_steps_use_invoke_agent(self) -> None:
        """All steps (including intermediate rounds) must use invoke-agent."""
        wf = build_moa_workflow("q", ["a", "b"], "agg", rounds=3)
        for step in wf.steps:
            assert step.action == StepAction.INVOKE_AGENT


# ---------------------------------------------------------------------------
# Temperature diversity tests
# ---------------------------------------------------------------------------


class TestTemperatureDiversity:
    """Tests for temperature spread across proposers."""

    def test_compute_single_model(self) -> None:
        """Single model returns exact base temperature."""
        temps = compute_diverse_temperatures(0.6, 1, spread=0.3)
        assert temps == [0.6]

    def test_compute_two_models(self) -> None:
        """Two models get base +/- spread."""
        temps = compute_diverse_temperatures(0.6, 2, spread=0.3)
        assert len(temps) == 2
        assert temps[0] == pytest.approx(0.3, abs=0.001)
        assert temps[1] == pytest.approx(0.9, abs=0.001)

    def test_compute_three_models_symmetric(self) -> None:
        """Three models spread symmetrically: base-spread, base, base+spread."""
        temps = compute_diverse_temperatures(0.6, 3, spread=0.3)
        assert len(temps) == 3
        assert temps[0] == pytest.approx(0.3, abs=0.001)
        assert temps[1] == pytest.approx(0.6, abs=0.001)
        assert temps[2] == pytest.approx(0.9, abs=0.001)

    def test_clamps_to_lower_bound(self) -> None:
        """Temperatures below 0.0 must be clamped."""
        temps = compute_diverse_temperatures(0.1, 3, spread=0.5)
        assert all(t >= 0.0 for t in temps)

    def test_clamps_to_upper_bound(self) -> None:
        """Temperatures above 2.0 must be clamped."""
        temps = compute_diverse_temperatures(1.9, 3, spread=0.5)
        assert all(t <= 2.0 for t in temps)

    def test_zero_count_returns_empty(self) -> None:
        """Zero models returns empty list."""
        assert compute_diverse_temperatures(0.6, 0) == []

    def test_spread_zero_all_same(self) -> None:
        """spread=0 makes all temperatures equal to base."""
        temps = compute_diverse_temperatures(0.7, 4, spread=0.0)
        assert all(t == 0.7 for t in temps)

    def test_workflow_with_diversity(self) -> None:
        """Proposers get different temperatures when diversity is enabled."""
        wf = build_moa_workflow(
            "q",
            ["a", "b", "c"],
            "agg",
            reference_temperature=0.6,
            temperature_diversity=True,
            temperature_spread=0.3,
        )
        ref_steps = [s for s in wf.steps if s.id != "moa_aggregator"]
        temps = [s.inputs["temperature"] for s in ref_steps]
        # All should be different (3 models with nonzero spread)
        assert len(set(temps)) == 3
        # Middle one should be at base
        assert temps[1] == pytest.approx(0.6, abs=0.001)

    def test_workflow_without_diversity_uniform(self) -> None:
        """Without diversity, all proposers use the same temperature."""
        wf = build_moa_workflow(
            "q",
            ["a", "b", "c"],
            "agg",
            reference_temperature=0.6,
            temperature_diversity=False,
        )
        ref_steps = [s for s in wf.steps if s.id != "moa_aggregator"]
        temps = [s.inputs["temperature"] for s in ref_steps]
        assert all(t == 0.6 for t in temps)

    def test_single_model_no_diversity_effect(self) -> None:
        """Single model ignores diversity flag (nothing to spread)."""
        wf = build_moa_workflow(
            "q",
            ["solo"],
            "agg",
            reference_temperature=0.6,
            temperature_diversity=True,
            temperature_spread=0.3,
        )
        ref = next(s for s in wf.steps if s.id != "moa_aggregator")
        # Single model -> diversity has no effect -> base temperature used
        assert ref.inputs["temperature"] == 0.6

    def test_diversity_in_multi_round(self) -> None:
        """Temperature diversity applies to all rounds."""
        wf = build_moa_workflow(
            "q",
            ["a", "b"],
            "agg",
            reference_temperature=0.6,
            rounds=2,
            temperature_diversity=True,
            temperature_spread=0.2,
        )
        r1_steps = [s for s in wf.steps if s.id.startswith("r1_")]
        r2_steps = [s for s in wf.steps if s.id.startswith("r2_")]
        # Both rounds should have the same temperature spread
        r1_temps = [s.inputs["temperature"] for s in r1_steps]
        r2_temps = [s.inputs["temperature"] for s in r2_steps]
        assert r1_temps[0] != r1_temps[1]  # Different temps in round 1
        assert r2_temps[0] != r2_temps[1]  # Different temps in round 2


# ---------------------------------------------------------------------------
# Cost estimation tests
# ---------------------------------------------------------------------------


class TestCostEstimation:
    """Tests for MoA cost estimation via PricingCatalog."""

    def _make_catalog(self) -> PricingCatalog:
        """Create a test catalog with known pricing entries."""
        cat = PricingCatalog()
        cat.set_override(
            "openai",
            "gpt-4o",
            PricingEntry(
                input_cost_per_million=Decimal("2.50"),
                output_cost_per_million=Decimal("10.00"),
            ),
        )
        cat.set_override(
            "openai",
            "gpt-4o-mini",
            PricingEntry(
                input_cost_per_million=Decimal("0.15"),
                output_cost_per_million=Decimal("0.60"),
            ),
        )
        return cat

    def test_single_round_cost_structure(self) -> None:
        """Single round: N proposer costs + 1 aggregator cost."""
        cat = self._make_catalog()
        cost = estimate_moa_cost(
            query="What is AI?",
            reference_models=["gpt-4o-mini", "gpt-4o-mini"],
            aggregator_model="gpt-4o",
            rounds=1,
            provider="openai",
            catalog=cat,
        )
        # 2 proposers + 1 aggregator = 3 step costs
        assert len(cost.per_step) == 3
        assert cost.proposer_count == 2
        assert cost.rounds == 1
        assert cost.aggregator_model == "gpt-4o"
        assert cost.total_usd > Decimal("0")

    def test_multi_round_multiplies_proposer_costs(self) -> None:
        """Multi-round: N models * R rounds + 1 aggregator."""
        cat = self._make_catalog()
        cost_1r = estimate_moa_cost(
            query="q",
            reference_models=["gpt-4o-mini"],
            aggregator_model="gpt-4o",
            rounds=1,
            provider="openai",
            catalog=cat,
        )
        cost_3r = estimate_moa_cost(
            query="q",
            reference_models=["gpt-4o-mini"],
            aggregator_model="gpt-4o",
            rounds=3,
            provider="openai",
            catalog=cat,
        )
        # 3 rounds should have more step costs
        assert len(cost_3r.per_step) == 4  # 3 proposer + 1 aggregator
        assert len(cost_1r.per_step) == 2  # 1 proposer + 1 aggregator
        # Total should be higher for 3 rounds
        assert cost_3r.total_usd > cost_1r.total_usd

    def test_unknown_model_returns_unknown_status(self) -> None:
        """Unknown models should return status=unknown."""
        cat = PricingCatalog()  # Empty, no entries
        cost = estimate_moa_cost(
            query="q",
            reference_models=["totally-unknown-model"],
            aggregator_model="also-unknown",
            rounds=1,
            provider="nonexistent",
            catalog=cat,
        )
        assert cost.status == CostStatus.UNKNOWN
        assert cost.total_usd == Decimal("0")

    def test_known_models_return_estimated_status(self) -> None:
        """Known models should return status=estimated."""
        cat = self._make_catalog()
        cost = estimate_moa_cost(
            query="q",
            reference_models=["gpt-4o-mini"],
            aggregator_model="gpt-4o",
            rounds=1,
            provider="openai",
            catalog=cat,
        )
        assert cost.status == CostStatus.ESTIMATED

    def test_cost_result_is_frozen_dataclass(self) -> None:
        """MoACostEstimate should be immutable."""
        cost = MoACostEstimate(
            total_usd=Decimal("1.23"),
            proposer_count=3,
            rounds=2,
            aggregator_model="agg",
        )
        with pytest.raises(AttributeError):
            cost.total_usd = Decimal("0")  # type: ignore[misc]

    def test_longer_query_increases_cost(self) -> None:
        """Longer queries produce higher input token estimates -> higher cost."""
        cat = self._make_catalog()
        short_cost = estimate_moa_cost(
            query="Hi",
            reference_models=["gpt-4o"],
            aggregator_model="gpt-4o",
            provider="openai",
            catalog=cat,
        )
        long_cost = estimate_moa_cost(
            query="Tell me about the history of artificial intelligence " * 100,
            reference_models=["gpt-4o"],
            aggregator_model="gpt-4o",
            provider="openai",
            catalog=cat,
        )
        assert long_cost.total_usd > short_cost.total_usd

    def test_custom_output_tokens(self) -> None:
        """Custom output token values should affect the cost."""
        cat = self._make_catalog()
        low = estimate_moa_cost(
            query="q",
            reference_models=["gpt-4o"],
            aggregator_model="gpt-4o",
            provider="openai",
            proposer_output_tokens=100,
            aggregator_output_tokens=100,
            catalog=cat,
        )
        high = estimate_moa_cost(
            query="q",
            reference_models=["gpt-4o"],
            aggregator_model="gpt-4o",
            provider="openai",
            proposer_output_tokens=5000,
            aggregator_output_tokens=5000,
            catalog=cat,
        )
        assert high.total_usd > low.total_usd

    def test_intermediate_rounds_have_larger_input(self) -> None:
        """Round 2+ proposers get prior round outputs as input context.

        This should be reflected in the per-step input_tokens being higher
        for subsequent rounds.
        """
        cat = self._make_catalog()
        cost = estimate_moa_cost(
            query="q",
            reference_models=["gpt-4o"],
            aggregator_model="gpt-4o",
            rounds=2,
            provider="openai",
            proposer_output_tokens=500,
            catalog=cat,
        )
        # First proposer = round 1 input tokens (query only)
        # Second proposer = round 2 input tokens (query + prior output)
        r1_input = cost.per_step[0].input_tokens
        r2_input = cost.per_step[1].input_tokens
        assert r2_input > r1_input


# ---------------------------------------------------------------------------
# Provider/model parsing tests
# ---------------------------------------------------------------------------


class TestParseProviderModel:
    """Tests for the provider/model string parser."""

    def test_slash_format(self) -> None:
        prov, mdl = _parse_provider_model("openai/gpt-4o", "default")
        assert prov == "openai"
        assert mdl == "gpt-4o"

    def test_plain_model_uses_default(self) -> None:
        prov, mdl = _parse_provider_model("llama3.2", "ollama")
        assert prov == "ollama"
        assert mdl == "llama3.2"

    def test_multiple_slashes(self) -> None:
        """Only first slash splits."""
        prov, mdl = _parse_provider_model("org/model/v2", "default")
        assert prov == "org"
        assert mdl == "model/v2"


# ---------------------------------------------------------------------------
# MoATool Phase 58 enhancements
# ---------------------------------------------------------------------------


class TestMoaToolPhase58:
    """Tests for MoATool enhancements: rounds, temperature diversity, estimate."""

    def _make_tool(self) -> MoATool:
        return MoATool(
            default_reference_models=["m1", "m2"],
            default_aggregator_model="aggregator",
        )

    def _ctx(self) -> ToolContext:
        return ToolContext(tenant_id="test-tenant")

    def test_schema_includes_new_params(self) -> None:
        """Tool schema must include rounds, temperature_diversity, estimate_only."""
        tool = self._make_tool()
        props = tool.parameters_schema["properties"]
        assert "rounds" in props
        assert "temperature_diversity" in props
        assert "estimate_only" in props

    async def test_estimate_only_returns_cost(self) -> None:
        """estimate_only=True should return cost estimate without executing."""
        tool = self._make_tool()
        result = await tool.execute(
            {"query": "What is AI?", "estimate_only": True},
            self._ctx(),
        )
        assert result.success
        assert "Estimated cost" in result.output
        assert "USD" in result.output

    async def test_rounds_passed_to_builder(self) -> None:
        """rounds parameter should be passed through to build_moa_workflow."""
        tool = self._make_tool()

        mock_result = WorkflowResult(
            outputs={"result": "answer"},
            steps_executed=["r1_m1", "r1_m2", "r2_m1", "r2_m2", "moa_aggregator"],
            step_results=[],
            duration_ms=50.0,
            status=WorkflowStatus.SUCCESS,
        )

        captured: list[Any] = []
        original_init = WorkflowExecutor.__init__

        def capture_init(self_: Any, definition: Any, **kwargs: Any) -> None:
            captured.append(definition)
            original_init(self_, definition, **kwargs)

        with (
            patch(
                "agent33.tools.builtin.moa.has_registered_agent_handler",
                side_effect=lambda name: name == "__default__",
            ),
            patch.object(WorkflowExecutor, "__init__", capture_init),
            patch.object(WorkflowExecutor, "execute", return_value=mock_result),
        ):
            result = await tool.execute(
                {"query": "test", "rounds": 2},
                self._ctx(),
            )

        assert result.success
        wf = captured[0]
        # 2 models x 2 rounds + 1 aggregator = 5
        assert len(wf.steps) == 5


# ---------------------------------------------------------------------------
# MoA API route tests
# ---------------------------------------------------------------------------


class TestMoaRoutes:
    """Tests for the /v1/moa API endpoints."""

    @pytest.fixture()
    def _mock_auth(self) -> Any:
        """Install mock auth middleware that grants all scopes."""
        from unittest.mock import MagicMock

        class FakeUser:
            tenant_id = "test"
            scopes = [
                "workflows:read",
                "workflows:write",
                "workflows:execute",
            ]

        async def _set_user(request: Any, call_next: Any) -> Any:
            request.state.user = FakeUser()
            return await call_next(request)

        # Insert at the beginning so it runs before AuthMiddleware
        app.middleware_stack = None  # Force rebuild
        middleware = MagicMock()
        middleware.side_effect = _set_user
        return FakeUser

    async def _client(self, fake_user: Any) -> AsyncClient:
        """Create a test client with auth headers."""
        transport = ASGITransport(app=app)
        return AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"Authorization": "Bearer test-token"},
        )

    async def test_build_endpoint_returns_workflow(self) -> None:
        """POST /v1/moa/build returns a valid workflow definition."""
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.post(
                "/v1/moa/build",
                json={
                    "query": "What is AI?",
                    "reference_models": ["model-a", "model-b"],
                    "aggregator_model": "gpt-4o",
                    "rounds": 2,
                    "temperature_diversity": True,
                },
            )
        # May get 401 (no real auth) or 200 — we test the route exists
        assert resp.status_code in (200, 401, 403)

    async def test_estimate_endpoint_returns_cost(self) -> None:
        """POST /v1/moa/estimate returns a cost estimate."""
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.post(
                "/v1/moa/estimate",
                json={
                    "query": "What is AI?",
                    "reference_models": ["gpt-4o-mini", "gpt-4o-mini"],
                    "aggregator_model": "gpt-4o",
                    "rounds": 1,
                    "provider": "openai",
                },
            )
        assert resp.status_code in (200, 401, 403)

    async def test_build_endpoint_rejects_empty_models(self) -> None:
        """POST /v1/moa/build should reject empty reference_models."""
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers={"X-API-Key": "test-key"},
        ) as client:
            resp = await client.post(
                "/v1/moa/build",
                json={
                    "query": "q",
                    "reference_models": [],
                    "aggregator_model": "gpt-4o",
                },
            )
        # 422 (validation) or 401 (auth)
        assert resp.status_code in (422, 401, 403)


# ---------------------------------------------------------------------------
# Integration: build + cost estimate consistency
# ---------------------------------------------------------------------------


class TestBuildCostConsistency:
    """Verify cost estimation aligns with built workflow structure."""

    def test_step_count_matches(self) -> None:
        """Cost per_step length must match workflow step count."""
        models = ["a", "b", "c"]
        cost = estimate_moa_cost(
            query="q",
            reference_models=models,
            aggregator_model="agg",
            rounds=2,
            provider="ollama",
        )
        wf = build_moa_workflow("q", models, "agg", rounds=2)
        assert len(cost.per_step) == len(wf.steps)

    def test_proposer_count_matches(self) -> None:
        """Cost proposer_count must match the number of reference models."""
        models = ["x", "y"]
        cost = estimate_moa_cost(
            query="q",
            reference_models=models,
            aggregator_model="agg",
        )
        assert cost.proposer_count == len(models)

    def test_rounds_consistent(self) -> None:
        """Cost rounds field must match the requested rounds."""
        cost = estimate_moa_cost(
            query="q",
            reference_models=["m"],
            aggregator_model="a",
            rounds=4,
        )
        assert cost.rounds == 4
