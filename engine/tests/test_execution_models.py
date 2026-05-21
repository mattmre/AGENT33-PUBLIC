"""Tests for execution contract Pydantic models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent33.execution.models import (
    AdapterDefinition,
    AdapterStatus,
    AdapterType,
    APIInterface,
    CLIInterface,
    ErrorHandling,
    ExecutionContract,
    ExecutionInputs,
    ExecutionResult,
    RetryConfig,
    SandboxConfig,
)


class TestSandboxConfig:
    """SandboxConfig defaults and bounds."""

    def test_defaults(self) -> None:
        cfg = SandboxConfig()
        assert cfg.timeout_ms == 30_000
        assert cfg.memory_mb == 512
        assert cfg.cpu_cores == 1
        assert cfg.filesystem.read == []
        assert cfg.network.enabled is False
        assert cfg.processes.max_children == 10

    def test_timeout_lower_bound(self) -> None:
        with pytest.raises(ValidationError):
            SandboxConfig(timeout_ms=500)

    def test_timeout_upper_bound(self) -> None:
        with pytest.raises(ValidationError):
            SandboxConfig(timeout_ms=700_000)

    def test_memory_bounds(self) -> None:
        with pytest.raises(ValidationError):
            SandboxConfig(memory_mb=32)
        with pytest.raises(ValidationError):
            SandboxConfig(memory_mb=8192)

    def test_cpu_cores_bounds(self) -> None:
        with pytest.raises(ValidationError):
            SandboxConfig(cpu_cores=0)
        with pytest.raises(ValidationError):
            SandboxConfig(cpu_cores=8)


class TestExecutionContract:
    """ExecutionContract creation and defaults."""

    def test_minimal_contract(self) -> None:
        c = ExecutionContract(
            tool_id="TL-001",
            inputs=ExecutionInputs(command="echo"),
        )
        assert c.tool_id == "TL-001"
        assert c.inputs.command == "echo"
        assert c.execution_id  # auto-generated UUID
        assert c.adapter_id is None
        assert c.sandbox.timeout_ms == 30_000

    def test_full_contract(self) -> None:
        c = ExecutionContract(
            execution_id="test-id",
            tool_id="TL-002",
            adapter_id="ADP-001",
            inputs=ExecutionInputs(
                command="rg",
                arguments=["--json", "pattern"],
                environment={"LANG": "C"},
                working_directory="/tmp",
                input_files=["/tmp/a.txt"],
                stdin="hello",
            ),
            sandbox=SandboxConfig(timeout_ms=5000, memory_mb=256),
            metadata={"purpose": "test"},
        )
        assert c.execution_id == "test-id"
        assert c.adapter_id == "ADP-001"
        assert c.inputs.arguments == ["--json", "pattern"]
        assert c.sandbox.memory_mb == 256
        assert c.metadata["purpose"] == "test"


class TestExecutionResult:
    """ExecutionResult creation."""

    def test_success_result(self) -> None:
        r = ExecutionResult(
            execution_id="r-1",
            success=True,
            exit_code=0,
            stdout="hello\n",
            duration_ms=42.5,
        )
        assert r.success is True
        assert r.truncated is False
        assert r.error is None

    def test_failure_result(self) -> None:
        r = ExecutionResult(
            execution_id="r-2",
            success=False,
            exit_code=1,
            stderr="not found",
            error="Command failed",
        )
        assert r.success is False
        assert r.exit_code == 1


class TestAdapterDefinition:
    """AdapterDefinition with CLI and API interfaces."""

    def test_cli_adapter(self) -> None:
        d = AdapterDefinition(
            adapter_id="ADP-001",
            name="rg-search",
            tool_id="TL-003",
            type=AdapterType.CLI,
            cli=CLIInterface(
                executable="rg",
                base_args=["--json"],
                arg_mapping={"pattern": "{pattern}"},
            ),
        )
        assert d.type == AdapterType.CLI
        assert d.cli is not None
        assert d.cli.executable == "rg"
        assert d.status == AdapterStatus.ACTIVE

    def test_api_adapter(self) -> None:
        d = AdapterDefinition(
            adapter_id="ADP-002",
            name="rest-client",
            tool_id="TL-100",
            type=AdapterType.API,
            api=APIInterface(
                base_url="https://api.example.com",
                auth_method="bearer",
            ),
        )
        assert d.api is not None
        assert d.api.base_url == "https://api.example.com"

    def test_serialization_roundtrip(self) -> None:
        d = AdapterDefinition(
            adapter_id="ADP-RT",
            name="roundtrip",
            tool_id="TL-RT",
            type=AdapterType.CLI,
            cli=CLIInterface(executable="echo"),
            error_handling=ErrorHandling(
                retry=RetryConfig(max_attempts=3, backoff_ms=100),
            ),
            sandbox_override={"timeout_ms": 5000},
            metadata={"author": "test"},
        )
        data = d.model_dump()
        restored = AdapterDefinition.model_validate(data)
        assert restored.adapter_id == d.adapter_id
        assert restored.error_handling.retry.max_attempts == 3
        assert restored.sandbox_override == {"timeout_ms": 5000}
        assert restored.metadata["author"] == "test"
