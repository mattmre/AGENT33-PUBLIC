"""Integration test -- load a workflow, execute with mock LLM, verify output."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from agent33.testing.mock_llm import MockLLMProvider
from agent33.testing.workflow_harness import WorkflowTestHarness
from agent33.workflows.definition import WorkflowDefinition

if TYPE_CHECKING:
    from pathlib import Path

SIMPLE_WORKFLOW = {
    "name": "test-workflow",
    "version": "0.1.0",
    "description": "Integration test workflow",
    "steps": [
        {
            "id": "summarize",
            "action": "invoke-agent",
            "agent": "summarizer",
            "inputs": {"text": "Hello world"},
        },
        {
            "id": "validate",
            "action": "validate",
            "depends_on": ["summarize"],
            "inputs": {},
        },
    ],
    "execution": {"mode": "dependency-aware"},
}


@pytest.fixture()
def workflow_file(tmp_path: Path) -> Path:
    """Write the test workflow to a temp file and return its path."""
    path = tmp_path / "test-workflow.json"
    path.write_text(json.dumps(SIMPLE_WORKFLOW), encoding="utf-8")
    return path


class TestWorkflowExecution:
    """End-to-end workflow execution with mocked agents."""

    def test_load_workflow_from_file(self, workflow_file: Path) -> None:
        harness = WorkflowTestHarness()
        defn = harness.load_workflow(workflow_file)
        assert defn.name == "test-workflow"
        assert len(defn.steps) == 2

    def test_dry_run_lists_steps(self, workflow_file: Path) -> None:
        harness = WorkflowTestHarness()
        harness.load_workflow(workflow_file)
        result = harness.dry_run(inputs={"text": "Hello world"})

        assert result.workflow_name == "test-workflow"
        assert result.total_steps == 2
        assert "summarize" in result.execution_order
        assert "validate" in result.execution_order
        # summarize must come before validate
        assert result.execution_order.index("summarize") < result.execution_order.index("validate")

    @pytest.mark.asyncio
    async def test_run_with_mocks(self, workflow_file: Path) -> None:
        harness = WorkflowTestHarness()
        harness.load_workflow(workflow_file)

        mock_agents = {
            "summarizer": {"summary": "A short summary"},
        }

        result = await harness.run_with_mocks(
            inputs={"text": "Hello world"},
            mock_agents=mock_agents,
        )

        assert result.success is True
        assert result.workflow_name == "test-workflow"
        assert len(result.step_results) == 2
        assert result.step_results[0].step_id == "summarize"
        assert result.step_results[0].output == {"summary": "A short summary"}

    def test_load_definition_directly(self) -> None:
        defn = WorkflowDefinition.model_validate(SIMPLE_WORKFLOW)
        harness = WorkflowTestHarness()
        harness.load_definition(defn)
        result = harness.dry_run()
        assert result.total_steps == 2

    @pytest.mark.asyncio
    async def test_mock_llm_provider_deterministic(self) -> None:
        provider = MockLLMProvider({"hello": "world"})
        from agent33.llm.base import ChatMessage

        response = await provider.complete(
            [ChatMessage(role="user", content="hello")],
            model="test",
        )
        assert response.content == "world"

    @pytest.mark.asyncio
    async def test_mock_llm_provider_echo_fallback(self) -> None:
        provider = MockLLMProvider()
        from agent33.llm.base import ChatMessage

        response = await provider.complete(
            [ChatMessage(role="user", content="echo this")],
            model="test",
        )
        assert response.content == "echo this"
