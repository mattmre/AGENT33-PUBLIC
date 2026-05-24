"""Regression coverage for the canned agent test harness."""

from __future__ import annotations

import json

import pytest

from agent33.agents.definition import AgentDefinition
from agent33.testing.agent_harness import AgentTestHarness


@pytest.mark.asyncio
async def test_run_regression_executes_canned_pass_fail_pairs() -> None:
    definition = AgentDefinition.model_validate(
        {
            "name": "test-engineer",
            "version": "1.0.0",
            "role": "test-engineer",
            "description": "Runs deterministic canned regression checks.",
            "inputs": {
                "acceptance_criteria": {
                    "type": "string",
                    "description": "Criterion under test",
                    "required": True,
                }
            },
            "outputs": {
                "test_evidence": {
                    "type": "object",
                    "description": "Regression verdict",
                }
            },
        }
    )
    pass_input = {"acceptance_criteria": "criteria with complete evidence"}
    pass_output = {"test_evidence": {"status": "pass", "reason": "evidence matched"}}
    fail_input = {"acceptance_criteria": "criteria with missing evidence"}
    fail_output = {"test_evidence": {"status": "fail", "reason": "evidence missing"}}

    harness = AgentTestHarness()
    harness.load_definition(definition)
    harness.add_canned_pair(pass_input, pass_output)
    harness.add_canned_pair(fail_input, fail_output)

    results = await harness.run_regression(
        responses={
            json.dumps(pass_input, indent=2): json.dumps(pass_output),
            json.dumps(fail_input, indent=2): json.dumps(fail_output),
        }
    )

    assert [pair.input_data for pair, _ in results] == [pass_input, fail_input]
    assert [pair.expected_output for pair, _ in results] == [pass_output, fail_output]
    assert [result.output for _, result in results] == [pass_output, fail_output]
    assert all(result.model == "mock" for _, result in results)
