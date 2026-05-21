"""Tests for the Mixture-of-Agents (MoA) workflow template and tool.

Validates DAG structure, step dependencies, config integration, and tool
execution with mocked workflow infrastructure.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agent33.config import Settings
from agent33.tools.base import ToolContext
from agent33.tools.builtin.moa import MoATool
from agent33.workflows.dag import DAGBuilder
from agent33.workflows.definition import (
    ExecutionMode,
    StepAction,
)
from agent33.workflows.executor import WorkflowExecutor, WorkflowResult, WorkflowStatus
from agent33.workflows.templates.mixture_of_agents import (
    MOA_AGGREGATOR_SYSTEM_PROMPT,
    _make_unique_ids,
    _sanitize_step_id,
    build_moa_workflow,
    format_moa_result,
)

# ---------------------------------------------------------------------------
# Workflow builder tests
# ---------------------------------------------------------------------------


class TestBuildMoaWorkflow:
    """Tests for the ``build_moa_workflow`` function."""

    def test_creates_correct_number_of_steps(self) -> None:
        """N reference models + 1 aggregator = N+1 total steps."""
        models = ["llama3.2", "mistral", "gemma2"]
        wf = build_moa_workflow("What is 2+2?", models, "gpt-4o")
        assert len(wf.steps) == 4  # 3 refs + 1 aggregator

    def test_reference_steps_have_no_dependencies(self) -> None:
        """All reference steps must be independent (no depends_on)."""
        models = ["model-a", "model-b"]
        wf = build_moa_workflow("test query", models, "aggregator-model")
        ref_steps = [s for s in wf.steps if s.id != "moa_aggregator"]
        for step in ref_steps:
            assert step.depends_on == [], f"Step {step.id} should have no dependencies"

    def test_aggregator_depends_on_all_reference_steps(self) -> None:
        """The aggregator step must depend on every reference step."""
        models = ["alpha", "beta", "gamma"]
        wf = build_moa_workflow("test", models, "synth")
        ref_ids = {s.id for s in wf.steps if s.id != "moa_aggregator"}
        agg = next(s for s in wf.steps if s.id == "moa_aggregator")
        assert set(agg.depends_on) == ref_ids

    def test_aggregator_has_system_prompt(self) -> None:
        """The aggregator step must carry the MoA system prompt."""
        wf = build_moa_workflow("Hello", ["model-a"], "model-b")
        agg = next(s for s in wf.steps if s.id == "moa_aggregator")
        assert agg.inputs["system_prompt"] == MOA_AGGREGATOR_SYSTEM_PROMPT

    def test_aggregator_prompt_references_all_ref_steps(self) -> None:
        """The aggregator user prompt must include Jinja2 refs for each ref step."""
        models = ["model-a", "model-b"]
        wf = build_moa_workflow("question", models, "agg")
        agg = next(s for s in wf.steps if s.id == "moa_aggregator")
        prompt: str = agg.inputs["prompt"]
        ref_ids = [s.id for s in wf.steps if s.id != "moa_aggregator"]
        for ref_id in ref_ids:
            assert ref_id in prompt, f"Aggregator prompt must reference {ref_id}"

    def test_execution_mode_is_dependency_aware(self) -> None:
        """The workflow must use dependency-aware execution for DAG scheduling."""
        wf = build_moa_workflow("q", ["m1", "m2"], "agg")
        assert wf.execution.mode == ExecutionMode.DEPENDENCY_AWARE

    def test_parallel_limit_matches_reference_count(self) -> None:
        """Parallel limit should match the number of reference models."""
        models = ["a", "b", "c", "d"]
        wf = build_moa_workflow("q", models, "synth")
        assert wf.execution.parallel_limit == 4

    def test_temperatures_propagate_to_steps(self) -> None:
        """Custom temperatures must appear in step inputs."""
        wf = build_moa_workflow("q", ["m1"], "agg", 0.9, 0.1)
        ref = next(s for s in wf.steps if s.id != "moa_aggregator")
        agg = next(s for s in wf.steps if s.id == "moa_aggregator")
        assert ref.inputs["temperature"] == 0.9
        assert agg.inputs["temperature"] == 0.1

    def test_step_ids_are_valid(self) -> None:
        """All step IDs must match the WorkflowStep pattern ^[a-z][a-z0-9_-]*$."""
        import re

        pattern = re.compile(r"^[a-z][a-z0-9_-]*$")
        wf = build_moa_workflow("q", ["GPT-4o", "Claude-3.5", "Llama-3.2"], "gpt-4o")
        for step in wf.steps:
            assert pattern.match(step.id), f"Invalid step ID: {step.id}"

    def test_all_steps_use_invoke_agent_action(self) -> None:
        """Both reference and aggregator steps must use invoke-agent."""
        wf = build_moa_workflow("q", ["m1", "m2"], "agg")
        for step in wf.steps:
            assert step.action == StepAction.INVOKE_AGENT

    def test_empty_reference_models_raises(self) -> None:
        """Must reject an empty reference model list."""
        with pytest.raises(ValueError, match="At least one reference model"):
            build_moa_workflow("q", [], "agg")

    def test_workflow_metadata_tags(self) -> None:
        """Workflow metadata should include MoA-related tags."""
        wf = build_moa_workflow("q", ["m1"], "agg")
        assert "moa" in wf.metadata.tags
        assert "multi-model" in wf.metadata.tags

    def test_single_reference_model(self) -> None:
        """A single reference model should still produce a valid workflow."""
        wf = build_moa_workflow("q", ["sole-model"], "agg")
        assert len(wf.steps) == 2
        ref = wf.steps[0]
        agg = wf.steps[1]
        assert agg.depends_on == [ref.id]

    def test_model_name_in_step_inputs(self) -> None:
        """Each step must carry its model name in inputs for downstream routing."""
        wf = build_moa_workflow("q", ["llama3.2"], "gpt-4o")
        ref = next(s for s in wf.steps if s.id != "moa_aggregator")
        agg = next(s for s in wf.steps if s.id == "moa_aggregator")
        assert ref.inputs["agent_name"] == "llama3.2"
        assert ref.inputs["model"] == "llama3.2"
        assert agg.inputs["agent_name"] == "gpt-4o"
        assert agg.inputs["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# DAG structure tests
# ---------------------------------------------------------------------------


class TestMoaDagStructure:
    """Verify the generated workflow forms a valid DAG."""

    def test_dag_builds_without_cycles(self) -> None:
        """The MoA workflow DAG must be cycle-free."""
        wf = build_moa_workflow("q", ["a", "b", "c"], "synth")
        dag = DAGBuilder(wf.steps).build()
        order = dag.topological_order()
        assert len(order) == 4

    def test_dag_parallel_groups(self) -> None:
        """Reference steps form one parallel group, aggregator forms another."""
        wf = build_moa_workflow("q", ["a", "b", "c"], "synth")
        dag = DAGBuilder(wf.steps).build()
        groups = dag.parallel_groups()
        assert len(groups) == 2
        # First group: all 3 reference steps (independent)
        assert len(groups[0]) == 3
        # Second group: aggregator only
        assert groups[1] == ["moa_aggregator"]

    def test_topological_order_aggregator_last(self) -> None:
        """The aggregator must always come last in topological order."""
        wf = build_moa_workflow("q", ["x", "y"], "z")
        dag = DAGBuilder(wf.steps).build()
        order = dag.topological_order()
        assert order[-1] == "moa_aggregator"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestSanitizeStepId:
    """Tests for step ID sanitization."""

    def test_simple_name(self) -> None:
        assert _sanitize_step_id("llama3") == "llama3"

    def test_dots_replaced(self) -> None:
        assert _sanitize_step_id("gpt-4o.2024") == "gpt_4o_2024"

    def test_uppercase_lowered(self) -> None:
        assert _sanitize_step_id("GPT-4o") == "gpt_4o"

    def test_special_chars(self) -> None:
        result = _sanitize_step_id("model/v2@latest")
        assert result == "model_v2_latest"

    def test_numeric_start_prefixed(self) -> None:
        result = _sanitize_step_id("3.5-turbo")
        assert result.startswith("m_")

    def test_empty_string(self) -> None:
        result = _sanitize_step_id("")
        assert result == "model"


class TestMakeUniqueIds:
    """Tests for unique ID generation."""

    def test_distinct_models(self) -> None:
        pairs = _make_unique_ids(["alpha", "beta"])
        ids = [p[0] for p in pairs]
        assert len(ids) == len(set(ids))

    def test_duplicate_models_get_suffixes(self) -> None:
        pairs = _make_unique_ids(["same", "same", "same"])
        ids = [p[0] for p in pairs]
        assert len(ids) == 3
        assert len(set(ids)) == 3  # all unique
        # First one has no suffix, subsequent ones do
        assert ids[0] == "ref_same"
        assert ids[1] == "ref_same_1"
        assert ids[2] == "ref_same_2"


# ---------------------------------------------------------------------------
# format_moa_result tests
# ---------------------------------------------------------------------------


class TestFormatMoaResult:
    """Tests for result extraction."""

    def test_extracts_result_string(self) -> None:
        assert format_moa_result({"result": "Final answer"}) == "Final answer"

    def test_fallback_on_missing_result(self) -> None:
        out = format_moa_result({"other_key": "value"})
        assert "other_key" in out

    def test_empty_outputs(self) -> None:
        assert format_moa_result({}) == "(no aggregated response)"


# ---------------------------------------------------------------------------
# Config integration tests
# ---------------------------------------------------------------------------


class TestMoaConfig:
    """Tests for MoA configuration fields in Settings."""

    def test_default_values(self) -> None:
        s = Settings(
            environment="test",
            jwt_secret="test-secret-for-testing-only",
        )
        assert s.moa_reference_models == ""
        assert s.moa_aggregator_model == ""
        assert s.moa_reference_temperature == 0.6
        assert s.moa_aggregator_temperature == 0.4

    def test_custom_values(self) -> None:
        s = Settings(
            environment="test",
            jwt_secret="test-secret-for-testing-only",
            moa_reference_models="llama3.2,mistral,gemma2",
            moa_aggregator_model="gpt-4o",
            moa_reference_temperature=0.8,
            moa_aggregator_temperature=0.2,
        )
        assert s.moa_reference_models == "llama3.2,mistral,gemma2"
        assert s.moa_aggregator_model == "gpt-4o"
        assert s.moa_reference_temperature == 0.8
        assert s.moa_aggregator_temperature == 0.2

    def test_parse_reference_models_from_csv(self) -> None:
        """Config stores models as CSV; consumer code splits them."""
        s = Settings(
            environment="test",
            jwt_secret="test-secret-for-testing-only",
            moa_reference_models="a,b,c",
        )
        models = [m.strip() for m in s.moa_reference_models.split(",") if m.strip()]
        assert models == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# MoATool tests
# ---------------------------------------------------------------------------


class TestMoaTool:
    """Tests for the MoATool wrapper."""

    def _make_tool(self, **kwargs: Any) -> MoATool:
        return MoATool(
            default_reference_models=kwargs.get("refs", ["m1", "m2"]),
            default_aggregator_model=kwargs.get("agg", "aggregator"),
            default_reference_temperature=kwargs.get("ref_temp", 0.6),
            default_aggregator_temperature=kwargs.get("agg_temp", 0.4),
        )

    def _make_context(self) -> ToolContext:
        return ToolContext(tenant_id="test-tenant")

    def _registered_handler_names(self, *names: str):
        registered_names = set(names)
        return patch(
            "agent33.tools.builtin.moa.has_registered_agent_handler",
            side_effect=lambda name: name in registered_names,
        )

    def test_name_and_description(self) -> None:
        tool = self._make_tool()
        assert tool.name == "mixture_of_agents"
        assert "Mixture-of-Agents" in tool.description

    def test_parameters_schema_has_query_required(self) -> None:
        tool = self._make_tool()
        schema = tool.parameters_schema
        assert "query" in schema["properties"]
        assert "query" in schema["required"]

    async def test_empty_query_fails(self) -> None:
        tool = self._make_tool()
        result = await tool.execute({"query": ""}, self._make_context())
        assert not result.success
        assert "No query" in result.error

    async def test_no_reference_models_fails(self) -> None:
        tool = MoATool(
            default_reference_models=[],
            default_aggregator_model="agg",
        )
        result = await tool.execute({"query": "hello"}, self._make_context())
        assert not result.success
        assert "reference models" in result.error.lower()

    async def test_no_aggregator_fails(self) -> None:
        tool = MoATool(
            default_reference_models=["m1"],
            default_aggregator_model="",
        )
        result = await tool.execute({"query": "hello"}, self._make_context())
        assert not result.success
        assert "aggregator" in result.error.lower()

    async def test_successful_execution(self) -> None:
        """Mock WorkflowExecutor to verify tool wiring end-to-end."""
        tool = self._make_tool()

        mock_result = WorkflowResult(
            outputs={"result": "Synthesized answer"},
            steps_executed=["ref_m1", "ref_m2", "moa_aggregator"],
            step_results=[],
            duration_ms=100.0,
            status=WorkflowStatus.SUCCESS,
        )
        mock_executor = AsyncMock()
        mock_executor.execute.return_value = mock_result

        with (
            self._registered_handler_names("__default__"),
            patch.object(
                WorkflowExecutor,
                "__init__",
                return_value=None,
            ),
            patch.object(
                WorkflowExecutor,
                "execute",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute({"query": "What is AI?"}, self._make_context())

        assert result.success
        assert result.output == "Synthesized answer"

    async def test_default_bridge_path_resolves_unknown_models(self) -> None:
        """Unknown model IDs should resolve through the shared bridge and preserve routing."""
        tool = self._make_tool()

        mock_result = WorkflowResult(
            outputs={"result": "Synthesized answer"},
            steps_executed=["ref_m1", "moa_aggregator"],
            step_results=[],
            duration_ms=100.0,
            status=WorkflowStatus.SUCCESS,
        )

        captured_definitions: list[Any] = []
        original_init = WorkflowExecutor.__init__

        def capture_init(
            self: Any,
            definition: Any,
            **kwargs: Any,
        ) -> None:
            captured_definitions.append(definition)
            original_init(self, definition, **kwargs)

        with (
            self._registered_handler_names("__default__"),
            patch.object(
                WorkflowExecutor,
                "__init__",
                capture_init,
            ),
            patch.object(
                WorkflowExecutor,
                "execute",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute({"query": "What is AI?"}, self._make_context())

        assert result.success
        assert result.output == "Synthesized answer"
        assert len(captured_definitions) == 1
        wf = captured_definitions[0]
        ref = next(s for s in wf.steps if s.id != "moa_aggregator")
        agg = next(s for s in wf.steps if s.id == "moa_aggregator")
        assert ref.agent == "__default__"
        assert agg.agent == "__default__"
        assert ref.inputs["agent_name"] == "m1"
        assert ref.inputs["model"] == "m1"
        assert agg.inputs["agent_name"] == "aggregator"
        assert agg.inputs["model"] == "aggregator"

    async def test_workflow_failure_returns_error(self) -> None:
        """When the workflow fails, the tool must return a ToolResult.fail."""
        tool = self._make_tool()

        from agent33.workflows.executor import StepResult

        mock_result = WorkflowResult(
            outputs={},
            steps_executed=["ref_m1"],
            step_results=[
                StepResult(
                    step_id="ref_m1",
                    status="failed",
                    error="model unavailable",
                )
            ],
            duration_ms=50.0,
            status=WorkflowStatus.FAILED,
        )

        with (
            self._registered_handler_names("__default__"),
            patch.object(
                WorkflowExecutor,
                "__init__",
                return_value=None,
            ),
            patch.object(
                WorkflowExecutor,
                "execute",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute({"query": "test"}, self._make_context())

        assert not result.success
        assert "model unavailable" in result.error

    async def test_params_override_defaults(self) -> None:
        """Explicit params should override tool defaults."""
        tool = self._make_tool()

        mock_result = WorkflowResult(
            outputs={"result": "answer"},
            steps_executed=["ref_custom1", "ref_custom2", "moa_aggregator"],
            step_results=[],
            duration_ms=50.0,
            status=WorkflowStatus.SUCCESS,
        )

        captured_definitions: list[Any] = []

        original_init = WorkflowExecutor.__init__

        def capture_init(
            self: Any,
            definition: Any,
            **kwargs: Any,
        ) -> None:
            captured_definitions.append(definition)
            original_init(self, definition, **kwargs)

        with (
            self._registered_handler_names("__default__"),
            patch.object(
                WorkflowExecutor,
                "__init__",
                capture_init,
            ),
            patch.object(
                WorkflowExecutor,
                "execute",
                return_value=mock_result,
            ),
        ):
            result = await tool.execute(
                {
                    "query": "test",
                    "reference_models": ["custom1", "custom2"],
                    "aggregator": "custom-agg",
                    "reference_temperature": 0.9,
                    "aggregator_temperature": 0.1,
                },
                self._make_context(),
            )

        assert result.success
        assert len(captured_definitions) == 1
        wf = captured_definitions[0]
        # Should have 2 ref steps + 1 aggregator = 3
        assert len(wf.steps) == 3
        ref_step = wf.steps[0]
        agg_step = next(s for s in wf.steps if s.id == "moa_aggregator")
        assert ref_step.inputs["temperature"] == 0.9
        assert agg_step.inputs["temperature"] == 0.1
        assert agg_step.inputs["model"] == "custom-agg"

    async def test_execution_exception_returns_error(self) -> None:
        """An unhandled exception in WorkflowExecutor should be caught."""
        tool = self._make_tool()

        with (
            self._registered_handler_names("__default__"),
            patch.object(
                WorkflowExecutor,
                "__init__",
                return_value=None,
            ),
            patch.object(
                WorkflowExecutor,
                "execute",
                side_effect=RuntimeError("connection refused"),
            ),
        ):
            result = await tool.execute({"query": "test"}, self._make_context())

        assert not result.success
        assert "connection refused" in result.error

    async def test_missing_bridge_returns_clear_failure(self) -> None:
        """If no exact agent or default bridge exists, execution should fail early."""
        tool = self._make_tool()

        with self._registered_handler_names():
            result = await tool.execute({"query": "test"}, self._make_context())

        assert not result.success
        assert "No workflow agent or __default__ bridge available" in result.error
