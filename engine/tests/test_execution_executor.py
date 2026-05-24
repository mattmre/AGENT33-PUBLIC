"""Tests for the central CodeExecutor pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from agent33.execution.adapters.base import BaseAdapter
from agent33.execution.executor import CodeExecutor
from agent33.execution.models import (
    AdapterDefinition,
    AdapterStatus,
    AdapterType,
    CLIInterface,
    ErrorHandling,
    ExecutionContract,
    ExecutionInputs,
    ExecutionResult,
    KernelContainerPolicy,
    KernelInterface,
    RetryConfig,
)


def _make_adapter(
    adapter_id: str = "adp-1",
    tool_id: str = "TL-001",
    status: AdapterStatus = AdapterStatus.ACTIVE,
    retryable_codes: list[int] | None = None,
    max_attempts: int = 1,
) -> BaseAdapter:
    """Create a mock adapter with the given properties."""
    defn = AdapterDefinition(
        adapter_id=adapter_id,
        name=f"mock-{adapter_id}",
        tool_id=tool_id,
        type=AdapterType.CLI,
        cli=CLIInterface(executable="echo"),
        status=status,
        error_handling=ErrorHandling(
            retry=RetryConfig(
                max_attempts=max_attempts,
                retryable_codes=retryable_codes or [],
            ),
        ),
        metadata={"sandbox_enforcement": "external"},
    )
    adapter = MagicMock(spec=BaseAdapter)
    adapter.adapter_id = adapter_id
    adapter.tool_id = tool_id
    adapter.definition = defn
    adapter.execute = AsyncMock(
        return_value=ExecutionResult(
            execution_id="test",
            success=True,
            exit_code=0,
            stdout="ok",
        ),
    )
    return adapter


def _make_contract(
    tool_id: str = "TL-001",
    adapter_id: str | None = None,
    command: str = "echo",
) -> ExecutionContract:
    return ExecutionContract(
        tool_id=tool_id,
        adapter_id=adapter_id,
        inputs=ExecutionInputs(command=command),
    )


class TestAdapterRegistration:
    """Register and resolve adapters."""

    def test_register_and_resolve_by_adapter_id(self) -> None:
        executor = CodeExecutor()
        adapter = _make_adapter(adapter_id="adp-1", tool_id="TL-001")
        executor.register_adapter(adapter)

        contract = _make_contract(adapter_id="adp-1")
        resolved = executor.resolve_adapter(contract)
        assert resolved is not None
        assert resolved.adapter_id == "adp-1"

    def test_resolve_by_tool_id(self) -> None:
        executor = CodeExecutor()
        adapter = _make_adapter(adapter_id="adp-1", tool_id="TL-001")
        executor.register_adapter(adapter)

        contract = _make_contract(tool_id="TL-001")
        resolved = executor.resolve_adapter(contract)
        assert resolved is not None
        assert resolved.tool_id == "TL-001"

    def test_resolve_not_found(self) -> None:
        executor = CodeExecutor()
        contract = _make_contract(tool_id="TL-999")
        assert executor.resolve_adapter(contract) is None

    def test_list_adapters_filtered(self) -> None:
        executor = CodeExecutor()
        executor.register_adapter(_make_adapter("a1", "TL-001"))
        executor.register_adapter(_make_adapter("a2", "TL-002"))

        all_defs = executor.list_adapters()
        assert len(all_defs) == 2

        filtered = executor.list_adapters(tool_id="TL-001")
        assert len(filtered) == 1
        assert filtered[0].tool_id == "TL-001"


class TestExecutePipeline:
    """Full execute() pipeline."""

    @pytest.mark.asyncio
    async def test_validation_failure_short_circuits(self) -> None:
        executor = CodeExecutor()
        adapter = _make_adapter()
        executor.register_adapter(adapter)

        # Shell metacharacters trigger IV-02 violation
        contract = _make_contract(command="echo")
        contract.inputs.arguments = ["hello; rm -rf /"]

        result = await executor.execute(contract)
        assert result.success is False
        assert "IV-02" in (result.error or "")
        adapter.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_blocked_tool_short_circuits(self) -> None:
        from agent33.tools.registry import ToolRegistry
        from agent33.tools.registry_entry import ToolRegistryEntry, ToolStatus

        registry = ToolRegistry()
        entry = ToolRegistryEntry(
            tool_id="TL-001",
            name="TL-001",
            version="1.0",
            status=ToolStatus.BLOCKED,
        )
        registry._entries["TL-001"] = entry

        executor = CodeExecutor(tool_registry=registry)
        adapter = _make_adapter()
        executor.register_adapter(adapter)

        contract = _make_contract()
        result = await executor.execute(contract)

        assert result.success is False
        assert "blocked" in (result.error or "").lower()
        adapter.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_registry_command_allowlist_blocks_disallowed_command(self) -> None:
        from agent33.tools.registry import ToolRegistry
        from agent33.tools.registry_entry import ToolRegistryEntry

        registry = ToolRegistry()
        registry._entries["TL-001"] = ToolRegistryEntry(
            tool_id="TL-001",
            name="TL-001",
            version="1.0",
            governance={"command_allowlist": ["python"]},
        )

        executor = CodeExecutor(tool_registry=registry)
        adapter = _make_adapter()
        executor.register_adapter(adapter)

        result = await executor.execute(_make_contract(command="curl"))

        assert result.success is False
        assert "IV-01" in (result.error or "")
        assert "allowlist" in (result.error or "")
        adapter.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_registry_command_denylist_blocks_even_when_allowed(self) -> None:
        from agent33.tools.registry import ToolRegistry
        from agent33.tools.registry_entry import ToolRegistryEntry

        registry = ToolRegistry()
        registry._entries["TL-001"] = ToolRegistryEntry(
            tool_id="TL-001",
            name="TL-001",
            version="1.0",
            governance={
                "command_allowlist": ["echo", "rm"],
                "deny_list": ["rm"],
            },
        )

        executor = CodeExecutor(tool_registry=registry)
        adapter = _make_adapter()
        executor.register_adapter(adapter)

        result = await executor.execute(_make_contract(command="rm"))

        assert result.success is False
        assert "explicitly denied" in (result.error or "")
        adapter.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_tool_registry_enables_late_startup_governance(self) -> None:
        from agent33.tools.registry import ToolRegistry
        from agent33.tools.registry_entry import ToolRegistryEntry

        registry = ToolRegistry()
        registry._entries["TL-001"] = ToolRegistryEntry(
            tool_id="TL-001",
            name="TL-001",
            version="1.0",
            governance={"command_allowlist": ["echo"]},
        )

        executor = CodeExecutor()
        executor.set_tool_registry(registry)
        adapter = _make_adapter()
        executor.register_adapter(adapter)

        result = await executor.execute(_make_contract(command="echo"))

        assert result.success is True
        adapter.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_adapter_not_found(self) -> None:
        executor = CodeExecutor()
        contract = _make_contract(tool_id="TL-MISSING")
        result = await executor.execute(contract)

        assert result.success is False
        assert "No adapter found" in (result.error or "")

    @pytest.mark.asyncio
    async def test_full_pipeline_success(self) -> None:
        executor = CodeExecutor()
        adapter = _make_adapter()
        executor.register_adapter(adapter)

        contract = _make_contract()
        result = await executor.execute(contract)

        assert result.success is True
        assert result.stdout == "ok"
        adapter.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_sandbox_override_merged(self) -> None:
        executor = CodeExecutor()
        adapter = _make_adapter()
        adapter.definition = adapter.definition.model_copy(
            update={"sandbox_override": {"timeout_ms": 5000}},
        )
        executor.register_adapter(adapter)

        contract = _make_contract()
        await executor.execute(contract)

        # Verify the adapter was called with a contract that has the merged timeout
        call_args = adapter.execute.call_args
        merged_contract = call_args[0][0]
        assert merged_contract.sandbox.timeout_ms == 5000

    @pytest.mark.asyncio
    async def test_unisolated_cli_adapter_fails_closed(self) -> None:
        executor = CodeExecutor()
        adapter = _make_adapter()
        adapter.definition = adapter.definition.model_copy(update={"metadata": {}})
        executor.register_adapter(adapter)

        result = await executor.execute(_make_contract(command="echo"))

        assert result.success is False
        assert "local CLI backend" in (result.error or "")
        assert "execution denied" in (result.error or "")
        adapter.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_local_kernel_adapter_fails_closed(self) -> None:
        executor = CodeExecutor()
        defn = AdapterDefinition(
            adapter_id="kernel-local",
            name="kernel-local",
            tool_id="TL-001",
            type=AdapterType.KERNEL,
            kernel=KernelInterface(container=KernelContainerPolicy(enabled=False)),
        )
        adapter = MagicMock(spec=BaseAdapter)
        adapter.adapter_id = "kernel-local"
        adapter.tool_id = "TL-001"
        adapter.definition = defn
        adapter.execute = AsyncMock(
            return_value=ExecutionResult(execution_id="test", success=True)
        )
        executor.register_adapter(adapter)

        result = await executor.execute(_make_contract(command="python"))

        assert result.success is False
        assert "local kernel backend" in (result.error or "")
        adapter.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_docker_kernel_adapter_is_allowed(self) -> None:
        executor = CodeExecutor()
        defn = AdapterDefinition(
            adapter_id="kernel-docker",
            name="kernel-docker",
            tool_id="TL-001",
            type=AdapterType.KERNEL,
            kernel=KernelInterface(container=KernelContainerPolicy(enabled=True)),
        )
        adapter = MagicMock(spec=BaseAdapter)
        adapter.adapter_id = "kernel-docker"
        adapter.tool_id = "TL-001"
        adapter.definition = defn
        adapter.execute = AsyncMock(
            return_value=ExecutionResult(execution_id="test", success=True, stdout="ok")
        )
        executor.register_adapter(adapter)

        result = await executor.execute(_make_contract(command="python"))

        assert result.success is True
        adapter.execute.assert_called_once()


class TestExecuteWithRetry:
    """execute_with_retry() logic."""

    @pytest.mark.asyncio
    async def test_no_retry_on_success(self) -> None:
        executor = CodeExecutor()
        adapter = _make_adapter(max_attempts=3, retryable_codes=[1])
        executor.register_adapter(adapter)

        contract = _make_contract()
        result = await executor.execute_with_retry(contract)
        assert result.success is True
        # execute was called through the pipeline (once for the successful attempt)
        assert adapter.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_retryable_code(self) -> None:
        executor = CodeExecutor()
        adapter = _make_adapter(max_attempts=3, retryable_codes=[1])

        # First two calls fail with retryable code, third succeeds
        adapter.execute = AsyncMock(
            side_effect=[
                ExecutionResult(execution_id="t", success=False, exit_code=1, error="fail1"),
                ExecutionResult(execution_id="t", success=False, exit_code=1, error="fail2"),
                ExecutionResult(execution_id="t", success=True, exit_code=0, stdout="ok"),
            ],
        )
        executor.register_adapter(adapter)

        contract = _make_contract()
        result = await executor.execute_with_retry(contract)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_code(self) -> None:
        executor = CodeExecutor()
        adapter = _make_adapter(max_attempts=3, retryable_codes=[1])
        adapter.execute = AsyncMock(
            return_value=ExecutionResult(
                execution_id="t", success=False, exit_code=127, error="not found"
            ),
        )
        executor.register_adapter(adapter)

        contract = _make_contract()
        result = await executor.execute_with_retry(contract)
        assert result.success is False
        assert result.exit_code == 127
        # Should not have retried
        assert adapter.execute.call_count == 1
