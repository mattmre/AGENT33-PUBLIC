"""Built-in hooks: MetricsHook, AuditLogHook."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from agent33.hooks.models import (
    HookDefinition,
    HookEventType,
)
from agent33.hooks.protocol import BaseHook

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from agent33.hooks.models import HookContext

logger = logging.getLogger(__name__)


class MetricsHook(BaseHook):
    """Observability hook that records timing and call count metrics.

    Priority 500 (observability tier). Fail-open. System-level (all tenants).
    Records hook chain invocation timestamps and durations into the metadata
    dict for downstream consumers (e.g., Prometheus exporter, telemetry).
    """

    def __init__(self) -> None:
        super().__init__(
            name="builtin.metrics",
            event_type="*",  # registers for all event types individually
            priority=500,
            enabled=True,
            tenant_id="",
        )
        self._call_counts: dict[str, int] = {}
        self._total_duration_ms: dict[str, float] = {}

    async def execute(
        self,
        context: HookContext,
        call_next: Callable[[HookContext], Awaitable[HookContext]],
    ) -> HookContext:
        """Record timing metrics around the downstream chain."""
        start = time.monotonic()
        result = await call_next(context)
        duration = (time.monotonic() - start) * 1000

        event = context.event_type
        self._call_counts[event] = self._call_counts.get(event, 0) + 1
        self._total_duration_ms[event] = self._total_duration_ms.get(event, 0.0) + duration

        result.metadata.setdefault("hook_metrics", {})
        result.metadata["hook_metrics"][event] = {
            "call_count": self._call_counts[event],
            "last_duration_ms": round(duration, 2),
            "total_duration_ms": round(self._total_duration_ms[event], 2),
        }

        return result

    @property
    def call_counts(self) -> dict[str, int]:
        """Expose call counts for testing / introspection."""
        return dict(self._call_counts)

    @property
    def total_duration_ms(self) -> dict[str, float]:
        """Expose cumulative durations for testing / introspection."""
        return dict(self._total_duration_ms)


class AuditLogHook(BaseHook):
    """Audit hook that logs every hook chain invocation.

    Priority 550 (observability tier). Fail-open. System-level (all tenants).
    Emits a structured log entry for each hook chain execution including
    the event type, tenant, and context summary.
    """

    def __init__(self) -> None:
        super().__init__(
            name="builtin.audit_log",
            event_type="*",
            priority=550,
            enabled=True,
            tenant_id="",
        )
        self._log_entries: list[dict[str, Any]] = []

    async def execute(
        self,
        context: HookContext,
        call_next: Callable[[HookContext], Awaitable[HookContext]],
    ) -> HookContext:
        """Log the hook invocation before delegating downstream."""
        entry: dict[str, Any] = {
            "event_type": context.event_type,
            "tenant_id": context.tenant_id,
            "timestamp": time.time(),
        }

        # Add context-specific fields without importing heavy types
        agent_name = getattr(context, "agent_name", None)
        if agent_name:
            entry["agent_name"] = agent_name
        tool_name = getattr(context, "tool_name", None)
        if tool_name:
            entry["tool_name"] = tool_name
        step_id = getattr(context, "step_id", None)
        if step_id:
            entry["step_id"] = step_id
        method = getattr(context, "method", None)
        if method is not None:
            entry["method"] = method
            entry["path"] = getattr(context, "path", "")

        self._log_entries.append(entry)
        logger.info("hook_audit event=%s tenant=%s", context.event_type, context.tenant_id)

        result = await call_next(context)
        return result

    @property
    def log_entries(self) -> list[dict[str, Any]]:
        """Expose log entries for testing / introspection."""
        return list(self._log_entries)


# ---------------------------------------------------------------------------
# Built-in hook factory
# ---------------------------------------------------------------------------

# Phase 1 event types (excluding wildcard-based builtins applied per-event)
_PHASE1_EVENT_TYPES = [
    HookEventType.AGENT_INVOKE_PRE,
    HookEventType.AGENT_INVOKE_POST,
    HookEventType.TOOL_EXECUTE_PRE,
    HookEventType.TOOL_EXECUTE_POST,
    HookEventType.WORKFLOW_STEP_PRE,
    HookEventType.WORKFLOW_STEP_POST,
    HookEventType.REQUEST_PRE,
    HookEventType.REQUEST_POST,
    # Phase 44: CLI session lifecycle
    HookEventType.SESSION_START,
    HookEventType.SESSION_END,
    HookEventType.SESSION_CHECKPOINT,
    HookEventType.SESSION_RESUME,
]


def get_builtin_hooks() -> list[tuple[Any, HookDefinition]]:
    """Return a list of (hook_instance, definition) pairs for all built-in hooks.

    Built-in hooks with event_type='*' are registered once for each Phase 1
    event type. Each registration gets a unique hook_id.
    """
    builtins: list[tuple[Any, HookDefinition]] = []

    # MetricsHook: register one instance per event type
    for event_type in _PHASE1_EVENT_TYPES:
        hook = MetricsHook()
        hook._event_type = event_type.value  # noqa: SLF001
        defn = HookDefinition(
            name=f"builtin.metrics.{event_type.value}",
            description="Built-in metrics collection hook",
            event_type=event_type,
            priority=500,
            handler_ref="agent33.hooks.builtins.MetricsHook",
            timeout_ms=200.0,
            enabled=True,
            tenant_id="",
            fail_mode="open",
            tags=["builtin", "observability"],
        )
        builtins.append((hook, defn))

    # AuditLogHook: register one instance per event type
    for event_type in _PHASE1_EVENT_TYPES:
        audit_hook = AuditLogHook()
        audit_hook._event_type = event_type.value  # noqa: SLF001
        defn = HookDefinition(
            name=f"builtin.audit_log.{event_type.value}",
            description="Built-in audit logging hook",
            event_type=event_type,
            priority=550,
            handler_ref="agent33.hooks.builtins.AuditLogHook",
            timeout_ms=200.0,
            enabled=True,
            tenant_id="",
            fail_mode="open",
            tags=["builtin", "observability"],
        )
        builtins.append((audit_hook, defn))

    return builtins
