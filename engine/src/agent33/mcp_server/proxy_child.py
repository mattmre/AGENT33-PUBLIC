"""Child server handle for a single proxied MCP server."""

from __future__ import annotations

import logging
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from agent33.connectors.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState

if TYPE_CHECKING:
    from agent33.mcp_server.proxy_models import ProxyServerConfig

logger = logging.getLogger(__name__)


class ChildServerState(StrEnum):
    """Lifecycle state for a proxied child server."""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    COOLDOWN = "cooldown"
    STOPPED = "stopped"


class ProxyToolDefinition:
    """Lightweight description of a tool discovered from a child server."""

    __slots__ = ("name", "description", "input_schema")

    def __init__(
        self,
        name: str,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema or {"type": "object", "properties": {}}


class ChildServerHandle:
    """Manages the lifecycle, health, and tool routing for a single child MCP server.

    In production, this would manage a subprocess and MCP client session.
    For Phase 45 the child is modelled in-memory with injectable tool
    definitions and a pluggable call handler, enabling deterministic tests
    without spawning real processes.
    """

    def __init__(
        self,
        config: ProxyServerConfig,
        circuit_breaker: CircuitBreaker | None = None,
        clock: Any | None = None,
    ) -> None:
        self.config = config
        self.state = ChildServerState.STOPPED
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=config.max_consecutive_failures,
            recovery_timeout_seconds=config.cooldown_seconds,
        )
        self._clock = clock or time.monotonic
        self.discovered_tools: dict[str, ProxyToolDefinition] = {}
        self.last_health_check: float = 0.0
        self.consecutive_failures: int = 0
        self.last_error: str = ""
        self.started_at: float = 0.0
        # Pluggable handler for tests / real MCP client integration
        self._call_handler: Any | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the child server (or mark as started for in-memory mode)."""
        if not self.config.enabled:
            self.state = ChildServerState.STOPPED
            return
        self.state = ChildServerState.STARTING
        self.started_at = self._clock()
        self.consecutive_failures = 0
        self.last_error = ""
        # In full integration this would spawn subprocess + MCP client.
        # For Phase 45, mark healthy immediately if tools are pre-registered.
        self.state = ChildServerState.HEALTHY
        logger.info(
            "proxy_child_started: id=%s name=%s",
            self.config.id,
            self.config.name,
        )

    async def stop(self) -> None:
        """Stop the child server."""
        self.state = ChildServerState.STOPPED
        self.discovered_tools.clear()
        logger.info("proxy_child_stopped: id=%s", self.config.id)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Run a health check.  Returns True if healthy."""
        self.last_health_check = self._clock()

        if self.state == ChildServerState.STOPPED:
            return False

        if self.state == ChildServerState.COOLDOWN:
            try:
                self.circuit_breaker.before_call()
            except CircuitOpenError:
                return False
            self.state = ChildServerState.DEGRADED

        # In production this would ping the child process.
        # For now, healthy if state is not explicitly failed.
        if self.state in (ChildServerState.HEALTHY, ChildServerState.DEGRADED):
            self.circuit_breaker.record_success()
            if self.circuit_breaker.state == CircuitState.CLOSED:
                self.state = ChildServerState.HEALTHY
                self.consecutive_failures = 0
            return True

        return False

    def record_failure(self, error: str = "") -> None:
        """Record a failure and potentially trip the circuit breaker."""
        self.consecutive_failures += 1
        self.last_error = error
        self.circuit_breaker.record_failure()

        if self.circuit_breaker.state == CircuitState.OPEN:
            self.state = ChildServerState.COOLDOWN
            logger.warning(
                "proxy_child_cooldown: id=%s failures=%d error=%s",
                self.config.id,
                self.consecutive_failures,
                error[:200],
            )
        elif self.state == ChildServerState.HEALTHY:
            self.state = ChildServerState.DEGRADED

    def record_success(self) -> None:
        """Record a successful call."""
        self.circuit_breaker.record_success()
        if self.circuit_breaker.state == CircuitState.CLOSED:
            self.state = ChildServerState.HEALTHY
            self.consecutive_failures = 0

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    def register_tools(self, tools: list[ProxyToolDefinition]) -> None:
        """Register tools discovered from the child server."""
        self.discovered_tools = {t.name: t for t in tools}

    def list_tools(self) -> list[ProxyToolDefinition]:
        """Return all discovered tools, respecting governance filters."""
        gov = self.config.governance
        result: list[ProxyToolDefinition] = []
        for tool in self.discovered_tools.values():
            if tool.name in gov.blocked_tools:
                continue
            if gov.allowed_tools != ["*"] and tool.name not in gov.allowed_tools:
                continue
            result.append(tool)
        return result

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call a tool on the child server."""
        try:
            self.circuit_breaker.before_call()
        except CircuitOpenError as exc:
            raise RuntimeError(f"Proxy server '{self.config.id}' is in cooldown") from exc

        if tool_name not in self.discovered_tools:
            raise ValueError(f"Tool '{tool_name}' not found on proxy server '{self.config.id}'")

        # Check governance
        gov = self.config.governance
        if gov.policy == "deny":
            raise PermissionError(f"Proxy server '{self.config.id}' has deny policy")
        if gov.policy == "ask":
            raise PermissionError(
                f"Proxy server '{self.config.id}' requires explicit approval before tool execution"
            )
        if tool_name in gov.blocked_tools:
            raise PermissionError(
                f"Tool '{tool_name}' is blocked on proxy server '{self.config.id}'"
            )

        try:
            if self._call_handler is None:
                raise RuntimeError(
                    f"Proxy server '{self.config.id}' has no tool execution handler"
                )
            result = await self._call_handler(tool_name, arguments)
            self.record_success()
            return result
        except Exception as exc:
            self.record_failure(str(exc))
            raise

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status_summary(self) -> dict[str, Any]:
        """Return a status summary dict for API responses."""
        uptime = 0.0
        if self.started_at and self.state != ChildServerState.STOPPED:
            uptime = self._clock() - self.started_at
        return {
            "id": self.config.id,
            "name": self.config.name or self.config.id,
            "state": self.state.value,
            "transport": self.config.transport,
            "tool_count": len(self.list_tools()),
            "uptime_seconds": round(uptime, 1),
            "consecutive_failures": self.consecutive_failures,
            "circuit_state": self.circuit_breaker.state.value,
            "last_health_check": self.last_health_check,
            "last_error": self.last_error or None,
        }
