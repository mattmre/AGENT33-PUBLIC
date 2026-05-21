"""Workflow action that dispatches a code execution contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agent33.execution.executor import CodeExecutor

logger = structlog.get_logger()

# Module-level executor, set during app startup via set_executor().
_executor: CodeExecutor | None = None


def set_executor(executor: CodeExecutor) -> None:
    """Wire the CodeExecutor so workflow steps can dispatch executions."""
    global _executor  # noqa: PLW0603
    _executor = executor


def get_executor() -> CodeExecutor:
    """Return the configured executor or raise."""
    if _executor is None:
        raise RuntimeError("CodeExecutor not configured — call set_executor() at startup")
    return _executor


async def execute(
    tool_id: str | None,
    adapter_id: str | None,
    inputs: dict[str, Any],
    sandbox: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build an ExecutionContract from workflow step data and dispatch it.

    Args:
        tool_id: Registered tool identifier.
        adapter_id: Optional explicit adapter to use.
        inputs: Resolved step inputs. Expected keys: ``command``,
            ``arguments``, ``environment``, ``working_directory``,
            ``input_files``, ``stdin``. Kernel-backed execution may also
            provide ``code``, ``language``, ``session_id``, and ``metadata``.
        sandbox: Optional sandbox overrides from the workflow step.
        dry_run: If True, log but skip actual execution.

    Returns:
        A dict with execution results suitable for workflow state.
    """
    if not tool_id:
        raise ValueError("execute-code action requires a 'tool_id'")

    logger.info(
        "execute_code_action",
        tool_id=tool_id,
        adapter_id=adapter_id,
        dry_run=dry_run,
    )

    if dry_run:
        return {
            "dry_run": True,
            "tool_id": tool_id,
            "adapter_id": adapter_id,
            "inputs": inputs,
        }

    from agent33.execution.models import (
        ExecutionContract,
        ExecutionInputs,
        SandboxConfig,
    )

    # Build ExecutionInputs from the step inputs dict.
    metadata = dict(inputs.get("metadata", {}) or {})
    if "session_id" in inputs and "session_id" not in metadata:
        metadata["session_id"] = inputs["session_id"]
    if "language" in inputs and "language" not in metadata:
        metadata["language"] = inputs["language"]

    exec_inputs = ExecutionInputs(
        command=inputs.get("command") or inputs.get("language", ""),
        arguments=inputs.get("arguments", []),
        environment=inputs.get("environment", {}),
        working_directory=inputs.get("working_directory"),
        input_files=inputs.get("input_files", []),
        stdin=inputs.get("stdin") or inputs.get("code"),
    )

    # Build optional sandbox config.
    sandbox_cfg = SandboxConfig(**(sandbox or {}))

    contract = ExecutionContract(
        tool_id=tool_id,
        adapter_id=adapter_id,
        inputs=exec_inputs,
        sandbox=sandbox_cfg,
        metadata=metadata,
    )

    executor = get_executor()
    result = await executor.execute_with_retry(contract)

    return {
        "execution_id": result.execution_id,
        "success": result.success,
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": result.duration_ms,
        "error": result.error,
        "truncated": result.truncated,
        "artifacts": [artifact.model_dump() for artifact in result.artifacts],
        "metadata": result.metadata,
    }
