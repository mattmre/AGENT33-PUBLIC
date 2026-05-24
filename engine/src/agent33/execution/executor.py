"""Central CodeExecutor — validates, resolves adapters, dispatches, and audits."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import structlog

from agent33.execution.models import (
    AdapterDefinition,
    AdapterStatus,
    AdapterType,
    ExecutionContract,
    ExecutionResult,
    SandboxConfig,
)
from agent33.execution.validation import validate_contract

if TYPE_CHECKING:
    from agent33.execution.adapters.base import BaseAdapter
    from agent33.tools.registry import ToolRegistry

logger = structlog.get_logger()


class CodeExecutor:
    """Orchestrates the full execution pipeline.

    Pipeline::

        validate_contract()
        -> check tool status (optional ToolRegistry integration)
        -> resolve adapter
        -> merge sandbox overrides
        -> dispatch to adapter
        -> audit log
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        command_allowlist: set[str] | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._command_allowlist = command_allowlist
        self._adapters: dict[str, BaseAdapter] = {}

    def set_tool_registry(self, tool_registry: ToolRegistry | None) -> None:
        """Attach the live ToolRegistry used for runtime governance."""
        self._tool_registry = tool_registry

    def set_command_allowlist(self, command_allowlist: set[str] | None) -> None:
        """Set a global fallback command allowlist for contracts without registry metadata."""
        self._command_allowlist = command_allowlist

    # ------------------------------------------------------------------
    # Adapter management
    # ------------------------------------------------------------------

    def register_adapter(self, adapter: BaseAdapter) -> None:
        """Register an adapter instance by its adapter_id."""
        self._adapters[adapter.adapter_id] = adapter
        logger.info(
            "adapter_registered",
            adapter_id=adapter.adapter_id,
            tool_id=adapter.tool_id,
        )

    def resolve_adapter(self, contract: ExecutionContract) -> BaseAdapter | None:
        """Find the best adapter for *contract*.

        Resolution order:
        1. Explicit ``adapter_id`` on the contract.
        2. First active adapter matching ``tool_id``.
        """
        # Explicit adapter_id
        if contract.adapter_id and contract.adapter_id in self._adapters:
            return self._adapters[contract.adapter_id]

        # Match by tool_id — first active adapter wins
        for adapter in self._adapters.values():
            if (
                adapter.tool_id == contract.tool_id
                and adapter.definition.status == AdapterStatus.ACTIVE
            ):
                return adapter

        return None

    def list_adapters(
        self,
        tool_id: str | None = None,
    ) -> list[AdapterDefinition]:
        """Return adapter definitions, optionally filtered by *tool_id*."""
        defs = [a.definition for a in self._adapters.values()]
        if tool_id is not None:
            defs = [d for d in defs if d.tool_id == tool_id]
        return defs

    # ------------------------------------------------------------------
    # Execution pipeline
    # ------------------------------------------------------------------

    async def execute(self, contract: ExecutionContract) -> ExecutionResult:
        """Run the full pipeline for a single contract."""
        start = time.monotonic()

        # 1. Validate
        command_allowlist, command_denylist = self._resolve_command_policy(contract)
        vr = validate_contract(
            contract,
            command_allowlist=command_allowlist,
            command_denylist=command_denylist,
        )
        if not vr.is_valid:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning(
                "contract_validation_failed",
                execution_id=contract.execution_id,
                violations=vr.violations,
            )
            return ExecutionResult(
                execution_id=contract.execution_id,
                success=False,
                error=f"Validation failed: {'; '.join(vr.violations)}",
                duration_ms=round(elapsed, 2),
            )

        # 2. Check tool status via ToolRegistry (optional)
        if self._tool_registry is not None:
            from agent33.tools.registry_entry import ToolStatus

            entry = self._tool_registry.get_entry(contract.tool_id)
            if entry is not None and entry.status == ToolStatus.BLOCKED:
                elapsed = (time.monotonic() - start) * 1000
                logger.warning(
                    "tool_blocked",
                    tool_id=contract.tool_id,
                    execution_id=contract.execution_id,
                )
                return ExecutionResult(
                    execution_id=contract.execution_id,
                    success=False,
                    error=f"Tool '{contract.tool_id}' is blocked",
                    duration_ms=round(elapsed, 2),
                )

        # 3. Resolve adapter
        adapter = self.resolve_adapter(contract)
        if adapter is None:
            elapsed = (time.monotonic() - start) * 1000
            return ExecutionResult(
                execution_id=contract.execution_id,
                success=False,
                error=(
                    f"No adapter found for tool_id='{contract.tool_id}'"
                    + (f", adapter_id='{contract.adapter_id}'" if contract.adapter_id else "")
                ),
                duration_ms=round(elapsed, 2),
            )

        # 4. Merge sandbox overrides from the adapter definition
        sandbox_data = contract.sandbox.model_dump()
        if adapter.definition.sandbox_override:
            sandbox_data = _deep_merge(sandbox_data, adapter.definition.sandbox_override)
        merged_sandbox = SandboxConfig.model_validate(sandbox_data)

        sandbox_error = self._validate_adapter_sandbox_enforcement(adapter, merged_sandbox)
        if sandbox_error is not None:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning(
                "adapter_sandbox_enforcement_failed",
                execution_id=contract.execution_id,
                adapter_id=adapter.adapter_id,
                error=sandbox_error,
            )
            return ExecutionResult(
                execution_id=contract.execution_id,
                success=False,
                error=sandbox_error,
                duration_ms=round(elapsed, 2),
            )

        contract_with_sandbox = contract.model_copy(
            update={"sandbox": merged_sandbox},
        )

        # 5. Dispatch
        result = await adapter.execute(contract_with_sandbox)

        # 6. Audit log
        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "execution_complete",
            execution_id=result.execution_id,
            adapter_id=adapter.adapter_id,
            success=result.success,
            exit_code=result.exit_code,
            duration_ms=round(elapsed, 2),
        )

        return result

    async def execute_with_retry(
        self,
        contract: ExecutionContract,
    ) -> ExecutionResult:
        """Execute with retry logic from the resolved adapter's config.

        Retries are attempted when the exit code is in the adapter's
        ``retryable_codes`` list.  Between retries the executor waits for
        ``backoff_ms`` milliseconds.
        """
        adapter = self.resolve_adapter(contract)

        # Determine retry parameters
        max_attempts = 1
        backoff_ms = 0
        retryable_codes: set[int] = set()

        if adapter is not None:
            retry_cfg = adapter.definition.error_handling.retry
            max_attempts = retry_cfg.max_attempts
            backoff_ms = retry_cfg.backoff_ms
            retryable_codes = set(retry_cfg.retryable_codes)

        last_result: ExecutionResult | None = None

        for attempt in range(1, max_attempts + 1):
            result = await self.execute(contract)
            last_result = result

            if result.success:
                return result

            if result.exit_code not in retryable_codes:
                return result

            if attempt < max_attempts:
                logger.info(
                    "execution_retry",
                    execution_id=contract.execution_id,
                    attempt=attempt,
                    exit_code=result.exit_code,
                    backoff_ms=backoff_ms,
                )
                if backoff_ms > 0:
                    await asyncio.sleep(backoff_ms / 1000.0)

        assert last_result is not None
        return last_result

    def _resolve_command_policy(
        self,
        contract: ExecutionContract,
    ) -> tuple[set[str] | None, set[str] | None]:
        """Resolve command allow/deny policy from registry metadata.

        Registry metadata is authoritative when present. The constructor
        allowlist remains a fallback for tests and standalone executors.
        """
        allowlist = self._command_allowlist
        denylist: set[str] | None = None
        if self._tool_registry is None:
            return allowlist, denylist

        entry = self._tool_registry.get_entry(contract.tool_id)
        if entry is None:
            return allowlist, denylist

        governance = entry.governance if isinstance(entry.governance, dict) else {}
        scope_commands = _string_set(getattr(entry.scope, "commands", []))
        governance_has_allowlist = "command_allowlist" in governance
        governance_commands = _string_set(governance.get("command_allowlist"))
        if governance_has_allowlist or scope_commands:
            allowlist = governance_commands | scope_commands

        deny_commands = _string_set(governance.get("deny_list"))
        deny_commands |= _string_set(governance.get("command_denylist"))
        deny_commands |= _string_set(governance.get("denylist"))
        if deny_commands:
            denylist = deny_commands

        return allowlist, denylist

    def _validate_adapter_sandbox_enforcement(
        self,
        adapter: BaseAdapter,
        sandbox: SandboxConfig,
    ) -> str | None:
        """Fail closed when a local adapter cannot enforce sandbox controls."""
        definition = adapter.definition
        enforcement = str(definition.metadata.get("sandbox_enforcement", "")).strip().lower()

        if definition.type == AdapterType.CLI:
            if enforcement in {"external", "isolated", "container", "sandboxed"}:
                return None
            return (
                f"Adapter '{adapter.adapter_id}' is a local CLI backend without declared "
                "sandbox_enforcement; execution denied because memory, CPU, filesystem, "
                "and network controls cannot be enforced by the local subprocess adapter"
            )

        if definition.type == AdapterType.KERNEL:
            container_enabled = bool(definition.kernel and definition.kernel.container.enabled)
            if container_enabled:
                return None
            if enforcement in {"external", "isolated", "container", "sandboxed"}:
                return None
            return (
                f"Adapter '{adapter.adapter_id}' is a local kernel backend without declared "
                "sandbox_enforcement; execution denied because memory, CPU, filesystem, "
                "and network controls cannot be enforced by the local kernel adapter"
            )

        del sandbox
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _string_set(value: Any) -> set[str]:
    """Normalize scalar/list policy values into a stripped string set."""
    if isinstance(value, str):
        return {value.strip()} if value.strip() else set()
    if isinstance(value, list):
        return {str(item).strip() for item in value if str(item).strip()}
    return set()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into a copy of *base*."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
