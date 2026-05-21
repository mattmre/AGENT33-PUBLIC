"""Central CodeExecutor — validates, resolves adapters, dispatches, and audits."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import structlog

from agent33.execution.models import (
    AdapterDefinition,
    AdapterStatus,
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
        vr = validate_contract(
            contract,
            command_allowlist=self._command_allowlist,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into a copy of *base*."""
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
