"""Tests for workflow execute-code action integration."""

from __future__ import annotations

from typing import Any

import pytest

from agent33.execution.models import ExecutionResult, OutputArtifact
from agent33.workflows.actions import execute_code


class _FakeExecutor:
    def __init__(self) -> None:
        self.contracts: list[Any] = []

    async def execute_with_retry(self, contract: Any) -> ExecutionResult:
        self.contracts.append(contract)
        return ExecutionResult(
            execution_id=contract.execution_id,
            success=True,
            stdout="ok",
            artifacts=[OutputArtifact(mime_type="text/html", data="<div>ok</div>")],
            metadata={"session_id": "sess-1", "kernel_name": "python3"},
        )


@pytest.mark.asyncio
async def test_execute_code_action_preserves_metadata_and_artifacts() -> None:
    fake_executor = _FakeExecutor()
    execute_code.set_executor(fake_executor)

    result = await execute_code.execute(
        tool_id="code-interpreter",
        adapter_id="jupyter-kernel",
        inputs={
            "code": "print('hi')",
            "language": "python",
            "session_id": "sess-1",
            "metadata": {"origin": "workflow"},
            "working_directory": "D:\\repo",
        },
        sandbox={"timeout_ms": 45_000},
    )

    contract = fake_executor.contracts[0]
    assert contract.inputs.command == "python"
    assert contract.inputs.stdin == "print('hi')"
    assert contract.metadata["session_id"] == "sess-1"
    assert contract.metadata["language"] == "python"
    assert contract.metadata["origin"] == "workflow"
    assert result["artifacts"] == [
        {"mime_type": "text/html", "data": "<div>ok</div>", "metadata": {}}
    ]
    assert result["metadata"]["session_id"] == "sess-1"
