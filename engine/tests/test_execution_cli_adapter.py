"""Tests for the CLI execution adapter."""

from __future__ import annotations

import sys

import pytest

from agent33.execution.adapters.cli import CLIAdapter
from agent33.execution.models import (
    AdapterDefinition,
    AdapterType,
    CLIInterface,
    ExecutionContract,
    ExecutionInputs,
    SandboxConfig,
)


def _cli_definition(
    executable: str = "python",
    base_args: list[str] | None = None,
) -> AdapterDefinition:
    return AdapterDefinition(
        adapter_id="test-cli",
        name="test-cli-adapter",
        tool_id="TL-TEST",
        type=AdapterType.CLI,
        cli=CLIInterface(
            executable=executable,
            base_args=base_args or [],
        ),
    )


def _contract(
    command: str = "python",
    arguments: list[str] | None = None,
    environment: dict[str, str] | None = None,
    timeout_ms: int = 10_000,
) -> ExecutionContract:
    return ExecutionContract(
        tool_id="TL-TEST",
        adapter_id="test-cli",
        inputs=ExecutionInputs(
            command=command,
            arguments=arguments or [],
            environment=environment or {},
        ),
        sandbox=SandboxConfig(timeout_ms=timeout_ms),
    )


class TestCLIAdapter:
    """CLI adapter subprocess execution."""

    @pytest.mark.asyncio
    async def test_successful_command(self) -> None:
        adapter = CLIAdapter(_cli_definition())
        contract = _contract(arguments=["-c", "print('hello')"])
        result = await adapter.execute(contract)

        assert result.success is True
        assert result.exit_code == 0
        assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_command_not_found(self) -> None:
        adapter = CLIAdapter(
            _cli_definition(executable="nonexistent_binary_xyz_999"),
        )
        contract = _contract()
        result = await adapter.execute(contract)

        assert result.success is False
        assert result.exit_code == 127
        # On Unix the error comes from FileNotFoundError (in result.error);
        # on Windows cmd.exe puts "is not recognized" in stderr.
        combined = ((result.error or "") + result.stderr).lower()
        assert "not found" in combined or "not recognized" in combined

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        # Sleep for 10 seconds but timeout after 1 second.
        if sys.platform == "win32":
            args = ["-c", "import time; time.sleep(10)"]
        else:
            args = ["-c", "import time; time.sleep(10)"]
        adapter = CLIAdapter(_cli_definition())
        contract = _contract(arguments=args, timeout_ms=1_000)
        result = await adapter.execute(contract)

        assert result.success is False
        assert result.exit_code == 143
        assert "timed out" in (result.error or "").lower()

    def test_missing_cli_interface_raises(self) -> None:
        defn = AdapterDefinition(
            adapter_id="no-cli",
            name="no-cli",
            tool_id="TL-X",
            type=AdapterType.CLI,
            cli=None,
        )
        with pytest.raises(ValueError, match="requires a 'cli' interface"):
            CLIAdapter(defn)

    @pytest.mark.asyncio
    async def test_environment_passthrough(self) -> None:
        adapter = CLIAdapter(_cli_definition())
        contract = _contract(
            arguments=["-c", "import os; print(os.environ.get('MY_VAR', ''))"],
            environment={"MY_VAR": "test_value"},
        )
        result = await adapter.execute(contract)

        assert result.success is True
        assert "test_value" in result.stdout
