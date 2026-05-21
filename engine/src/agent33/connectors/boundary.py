"""Shared connector-boundary construction and error mapping.

This module provides the central factory for building connector-boundary
middleware chains, policy-pack resolution, and a synchronous governance
enforcement helper for non-async adapter calls.

Policy Packs
~~~~~~~~~~~~
Three built-in policy packs are provided via ``_POLICY_PACKS``:

**default**
    No blocked connectors or operations.  All outbound calls pass through
    the middleware chain (governance, timeout, retry, circuit-breaker,
    metrics) but nothing is denied by default.  Suitable for development
    and trusted environments.

**strict-web**
    Blocks web-facing connectors that perform outbound HTTP requests on
    behalf of user-provided input: ``tool:web_fetch``,
    ``workflow:http_request``, ``search:searxng``, and ``tool:reader``.
    LLM provider calls and internal service communication remain
    unaffected.  Use this pack in environments where external web access
    must be prevented (e.g., air-gapped or compliance-restricted
    deployments).

**mcp-readonly**
    Blocks the MCP ``tools/call`` operation while leaving resource reads
    (``resources/read``, ``prompts/get``, etc.) open.  This allows agents
    to inspect MCP server capabilities without executing side-effecting
    tool calls.  Ideal for audit or monitoring contexts where MCP
    inspection is needed but execution must be suppressed.

Custom packs can be combined with per-instance blocklists via the
``CONNECTOR_GOVERNANCE_BLOCKED_CONNECTORS`` and
``CONNECTOR_GOVERNANCE_BLOCKED_OPERATIONS`` settings.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import structlog

from agent33.config import settings
from agent33.connectors.circuit_breaker import CircuitBreaker, CircuitOpenError
from agent33.connectors.executor import ConnectorExecutor
from agent33.connectors.governance import BlocklistConnectorPolicy
from agent33.connectors.middleware import (
    CircuitBreakerMiddleware,
    ConnectorMiddleware,
    GovernanceMiddleware,
    MetricsMiddleware,
    RetryMiddleware,
    TimeoutMiddleware,
)
from agent33.connectors.models import ConnectorRequest

if TYPE_CHECKING:
    from agent33.connectors.circuit_breaker import CircuitBreakerRegistry
    from agent33.connectors.monitoring import ConnectorMetricsCollector

logger = structlog.get_logger()


def _parse_csv(value: str) -> frozenset[str]:
    return frozenset(item.strip() for item in value.split(",") if item.strip())


# ---- Policy Pack definitions ------------------------------------------------
# Each entry maps a pack name to a tuple of
# (blocked_connectors: frozenset, blocked_operations: frozenset).
# Blocked connectors are matched against ConnectorRequest.connector;
# blocked operations are matched against ConnectorRequest.operation.
_POLICY_PACKS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    # No restrictions -- all calls are allowed.
    "default": (frozenset(), frozenset()),
    # Block outbound web crawling / fetching tools.
    "strict-web": (
        frozenset(
            {
                "tool:web_fetch",
                "workflow:http_request",
                "search:searxng",
                "tool:reader",
            }
        ),
        frozenset(),
    ),
    # Allow MCP resource reads but deny tool execution.
    "mcp-readonly": (
        frozenset(),
        frozenset({"tools/call"}),
    ),
}


def get_policy_pack(
    pack_name: str | None,
) -> tuple[frozenset[str], frozenset[str]]:
    """Return blocked connector/operation sets for the configured policy pack."""
    if not pack_name:
        return _POLICY_PACKS["default"]
    return _POLICY_PACKS.get(pack_name, _POLICY_PACKS["default"])


def _resolve_blocklists(policy_pack: str | None) -> tuple[frozenset[str], frozenset[str]]:
    pack_blocked_connectors, pack_blocked_operations = get_policy_pack(
        policy_pack or getattr(settings, "connector_policy_pack", "default")
    )
    blocked_connectors = pack_blocked_connectors.union(
        _parse_csv(settings.connector_governance_blocked_connectors)
    )
    blocked_operations = pack_blocked_operations.union(
        _parse_csv(settings.connector_governance_blocked_operations)
    )
    return blocked_connectors, blocked_operations


def enforce_connector_governance(
    connector: str,
    operation: str,
    *,
    policy_pack: str | None = None,
    payload: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Synchronously enforce connector governance for non-async adapter calls."""
    if not settings.connector_boundary_enabled:
        return

    blocked_connectors, blocked_operations = _resolve_blocklists(policy_pack)
    policy = BlocklistConnectorPolicy(
        blocked_connectors=blocked_connectors,
        blocked_operations=blocked_operations,
    )
    request = ConnectorRequest(
        connector=connector,
        operation=operation,
        payload=payload or {},
        metadata=metadata or {},
    )
    decision = policy.evaluate(request)
    if not decision.allowed:
        reason = decision.reason or "connector call blocked by governance policy"
        raise PermissionError(reason)


def build_connector_boundary_executor(
    *,
    default_timeout_seconds: float | None = None,
    retry_attempts: int = 1,
    policy_pack: str | None = None,
    metrics_collector: ConnectorMetricsCollector | None = None,
    breaker_registry: CircuitBreakerRegistry | None = None,
    connector_name: str | None = None,
) -> ConnectorExecutor | None:
    """Build the default connector boundary middleware chain.

    Parameters
    ----------
    metrics_collector:
        When provided, the :class:`MetricsMiddleware` will push call
        metrics to this collector for aggregation.
    breaker_registry:
        When provided (together with *connector_name*), breakers are
        shared per connector identity rather than created per executor.
    connector_name:
        Logical connector identity used to look up shared breakers in
        *breaker_registry*.
    """
    if not settings.connector_boundary_enabled:
        return None

    middlewares: list[ConnectorMiddleware] = []
    blocked_connectors, blocked_operations = _resolve_blocklists(policy_pack)
    policy = BlocklistConnectorPolicy(
        blocked_connectors=blocked_connectors,
        blocked_operations=blocked_operations,
    )
    middlewares.append(GovernanceMiddleware(policy))
    if default_timeout_seconds is not None:
        middlewares.append(TimeoutMiddleware(default_timeout_seconds))
    if retry_attempts > 1:
        middlewares.append(RetryMiddleware(max_attempts=retry_attempts))
    if settings.connector_circuit_breaker_enabled:
        breaker_kwargs: dict[str, Any] = {
            "failure_threshold": settings.connector_circuit_failure_threshold,
            "recovery_timeout_seconds": settings.connector_circuit_recovery_seconds,
            "half_open_success_threshold": settings.connector_circuit_half_open_successes,
            "max_recovery_timeout_seconds": settings.connector_circuit_max_recovery_seconds,
        }
        if breaker_registry is not None and connector_name:
            breaker = breaker_registry.get_or_create(connector_name, **breaker_kwargs)
        else:
            breaker = CircuitBreaker(**breaker_kwargs)
        # Wire metrics collector to circuit state changes
        if metrics_collector is not None:
            cname = connector_name or "unknown"
            coll = metrics_collector

            def _on_state_change(
                old: Any,
                new: Any,
                _cid: str = cname,
                _coll: ConnectorMetricsCollector = coll,
            ) -> None:
                _coll.record_circuit_event(_cid, str(old), str(new))

            breaker.on_state_change = _on_state_change
        middlewares.append(CircuitBreakerMiddleware(breaker))
    middlewares.append(MetricsMiddleware(collector=metrics_collector))
    logger.debug(
        "connector_boundary_executor_built",
        middleware_count=len(middlewares),
        connector_name=connector_name,
    )
    return ConnectorExecutor(middlewares=middlewares)


def map_connector_exception(exc: Exception, connector: str, operation: str) -> RuntimeError:
    """Normalize connector errors for consistent caller-facing failures."""
    if isinstance(exc, PermissionError):
        logger.warning(
            "connector_error_mapped",
            error_type="governance_blocked",
            connector=connector,
            operation=operation,
        )
        return RuntimeError(f"Connector governance blocked {connector}/{operation}: {exc}")
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        logger.warning(
            "connector_error_mapped",
            error_type="timeout",
            connector=connector,
            operation=operation,
        )
        return RuntimeError(f"Connector timeout for {connector}/{operation}: {exc}")
    if isinstance(exc, CircuitOpenError):
        logger.warning(
            "connector_error_mapped",
            error_type="circuit_open",
            connector=connector,
            operation=operation,
        )
        return RuntimeError(f"Connector circuit open for {connector}/{operation}: {exc}")
    if isinstance(exc, httpx.HTTPError):
        logger.warning(
            "connector_error_mapped",
            error_type="http_error",
            connector=connector,
            operation=operation,
        )
        return RuntimeError(f"Connector HTTP error for {connector}/{operation}: {exc}")
    logger.warning(
        "connector_error_mapped",
        error_type="general_failure",
        connector=connector,
        operation=operation,
    )
    return RuntimeError(f"Connector failure for {connector}/{operation}: {exc}")
