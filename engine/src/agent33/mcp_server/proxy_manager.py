"""MCP Proxy Manager: aggregates multiple upstream MCP servers."""

from __future__ import annotations

import logging
from typing import Any

from agent33.mcp_server.proxy_child import ChildServerHandle, ChildServerState
from agent33.mcp_server.proxy_models import ProxyFleetConfig, ProxyServerConfig

logger = logging.getLogger(__name__)

# The separator between prefix and tool name in aggregated tool listings.
DEFAULT_TOOL_SEPARATOR = "__"


class ProxyManager:
    """Central coordinator for the proxy fleet of child MCP servers."""

    def __init__(
        self,
        config: ProxyFleetConfig | None = None,
        tool_separator: str = DEFAULT_TOOL_SEPARATOR,
        health_check_enabled: bool = True,
    ) -> None:
        self._config = config or ProxyFleetConfig()
        self._tool_separator = tool_separator
        self._health_check_enabled = health_check_enabled
        self._children: dict[str, ChildServerHandle] = {}
        # Native tool names that should never be shadowed by proxy tools
        self._native_tool_names: set[str] = set()

    @property
    def tool_separator(self) -> str:
        """Return the configured proxy tool separator."""
        return self._tool_separator

    @property
    def health_check_enabled(self) -> bool:
        """Return whether on-demand health refreshes are enabled."""
        return self._health_check_enabled

    # ------------------------------------------------------------------
    # Fleet lifecycle
    # ------------------------------------------------------------------

    async def start_all(self) -> None:
        """Create handles for configured servers and start all enabled ones."""
        for server_cfg in self._config.proxy_servers:
            if server_cfg.id in self._children:
                logger.warning("proxy_duplicate_id: id=%s (skipping)", server_cfg.id)
                continue
            handle = ChildServerHandle(config=server_cfg)
            self._children[server_cfg.id] = handle
            if server_cfg.enabled:
                await handle.start()

    async def stop_all(self) -> None:
        """Stop all child servers in reverse-registration order."""
        for handle in reversed(list(self._children.values())):
            if handle.state != ChildServerState.STOPPED:
                await handle.stop()

    # ------------------------------------------------------------------
    # Server management
    # ------------------------------------------------------------------

    async def add_server(self, config: ProxyServerConfig) -> ChildServerHandle:
        """Add and start a new child server at runtime."""
        if config.id in self._children:
            raise ValueError(f"Proxy server '{config.id}' already registered")

        # Check for tool name collisions before adding
        handle = ChildServerHandle(config=config)
        self._children[config.id] = handle
        if config.enabled:
            await handle.start()
        return handle

    async def remove_server(self, server_id: str) -> bool:
        """Stop and remove a child server.  Returns True if found."""
        handle = self._children.pop(server_id, None)
        if handle is None:
            return False
        if handle.state != ChildServerState.STOPPED:
            await handle.stop()
        return True

    def get_server(self, server_id: str) -> ChildServerHandle | None:
        """Return a specific child server handle."""
        return self._children.get(server_id)

    def list_servers(self) -> list[dict[str, Any]]:
        """Return status summaries for all child servers."""
        return [h.status_summary() for h in self._children.values()]

    async def refresh_health(self) -> None:
        """Run on-demand health checks when enabled."""
        if not self._health_check_enabled:
            return
        for handle in self._children.values():
            await handle.health_check()

    # ------------------------------------------------------------------
    # Native tool registration (collision avoidance)
    # ------------------------------------------------------------------

    def set_native_tool_names(self, names: set[str]) -> None:
        """Register native AGENT-33 tool names to prevent proxy collisions."""
        self._native_tool_names = names

    # ------------------------------------------------------------------
    # Aggregated tool listing
    # ------------------------------------------------------------------

    def list_aggregated_tools(self) -> list[dict[str, Any]]:
        """Return all tools from all healthy children with prefixes applied."""
        tools: list[dict[str, Any]] = []
        for handle in self._children.values():
            if handle.state not in (ChildServerState.HEALTHY, ChildServerState.DEGRADED):
                continue
            prefix = handle.config.effective_prefix()
            for tool in handle.list_tools():
                prefixed_name = f"{prefix}{self._tool_separator}{tool.name}"
                tools.append(
                    {
                        "name": prefixed_name,
                        "description": f"[{prefix}] {tool.description}",
                        "inputSchema": tool.input_schema,
                        "proxy_server_id": handle.config.id,
                        "original_name": tool.name,
                    }
                )
        return tools

    def check_collisions(self) -> list[str]:
        """Check for tool name collisions across all children and native tools.

        Returns a list of collision descriptions (empty if clean).
        """
        collisions: list[str] = []
        seen: dict[str, str] = {}  # prefixed_name -> server_id

        for handle in self._children.values():
            prefix = handle.config.effective_prefix()
            for tool in handle.list_tools():
                prefixed_name = f"{prefix}{self._tool_separator}{tool.name}"
                if prefixed_name in self._native_tool_names:
                    collisions.append(
                        f"Proxy tool '{prefixed_name}' from server '{handle.config.id}' "
                        f"collides with native tool"
                    )
                elif prefixed_name in seen:
                    collisions.append(
                        f"Proxy tool '{prefixed_name}' from server '{handle.config.id}' "
                        f"collides with server '{seen[prefixed_name]}'"
                    )
                else:
                    seen[prefixed_name] = handle.config.id
        return collisions

    # ------------------------------------------------------------------
    # Tool routing
    # ------------------------------------------------------------------

    def resolve_server_for_tool(
        self, prefixed_tool_name: str
    ) -> tuple[ChildServerHandle, str] | None:
        """Map a prefixed tool name to (child, unprefixed_name).

        Returns None if no matching server is found.
        """
        for handle in self._children.values():
            if handle.state not in (ChildServerState.HEALTHY, ChildServerState.DEGRADED):
                continue
            prefix = handle.config.effective_prefix()
            expected_prefix = f"{prefix}{self._tool_separator}"
            if prefixed_tool_name.startswith(expected_prefix):
                unprefixed = prefixed_tool_name[len(expected_prefix) :]
                if unprefixed in handle.discovered_tools:
                    return handle, unprefixed
        return None

    async def call_proxy_tool(
        self,
        prefixed_tool_name: str,
        arguments: dict[str, Any],
    ) -> Any:
        """Route a tool call to the correct child server."""
        resolved = self.resolve_server_for_tool(prefixed_tool_name)
        if resolved is None:
            raise ValueError(f"No proxy server found for tool '{prefixed_tool_name}'")
        handle, unprefixed_name = resolved
        return await handle.call_tool(unprefixed_name, arguments)

    # ------------------------------------------------------------------
    # Fleet restart
    # ------------------------------------------------------------------

    async def restart_all(self) -> dict[str, Any]:
        """Restart every enabled server.  Returns per-server results."""
        restarted: list[str] = []
        failed: list[dict[str, str]] = []

        for server_id, handle in list(self._children.items()):
            if not handle.config.enabled:
                continue
            try:
                await handle.stop()
                await handle.start()
                restarted.append(server_id)
            except Exception as exc:
                failed.append({"id": server_id, "error": str(exc)})

        return {
            "restarted": restarted,
            "failed": failed,
            "total": len(restarted) + len(failed),
            "success_count": len(restarted),
            "failure_count": len(failed),
        }

    # ------------------------------------------------------------------
    # Hot-reload: config diffing and application
    # ------------------------------------------------------------------

    def _server_config_changed(self, old: ProxyServerConfig, new: ProxyServerConfig) -> bool:
        """Return True if the config for a server has materially changed."""
        return old.model_dump(exclude={"id"}) != new.model_dump(exclude={"id"})

    def diff_config(self, new_config: ProxyFleetConfig) -> dict[str, list[str]]:
        """Compute a diff between the current fleet and *new_config*.

        Returns ``{"to_add": [...], "to_remove": [...], "to_restart": [...],
        "unchanged": [...]}``.  Pure computation -- no side effects.
        """
        current_ids = set(self._children.keys())
        new_by_id = {s.id: s for s in new_config.proxy_servers}
        new_ids = set(new_by_id.keys())

        to_add = sorted(new_ids - current_ids)
        to_remove = sorted(current_ids - new_ids)
        to_restart: list[str] = []
        unchanged: list[str] = []

        for sid in sorted(current_ids & new_ids):
            old_cfg = self._children[sid].config
            new_cfg = new_by_id[sid]
            if self._server_config_changed(old_cfg, new_cfg):
                to_restart.append(sid)
            else:
                unchanged.append(sid)

        return {
            "to_add": to_add,
            "to_remove": to_remove,
            "to_restart": to_restart,
            "unchanged": unchanged,
        }

    async def reload_config(self, new_config: ProxyFleetConfig) -> dict[str, Any]:
        """Apply *new_config* to the running fleet.

        - Adds servers that are new in the config.
        - Removes servers no longer present.
        - Restarts servers whose config has changed.
        - Leaves unchanged servers untouched.

        Returns a structured result dict.
        """
        diff = self.diff_config(new_config)
        new_by_id = {s.id: s for s in new_config.proxy_servers}
        errors: list[dict[str, str]] = []

        # 1. Add new servers
        added: list[str] = []
        for sid in diff["to_add"]:
            try:
                await self.add_server(new_by_id[sid])
                added.append(sid)
            except Exception as exc:
                errors.append({"id": sid, "operation": "add", "error": str(exc)})

        # 2. Restart changed servers (stop old, replace config, start new)
        restarted: list[str] = []
        for sid in diff["to_restart"]:
            try:
                handle = self._children[sid]
                await handle.stop()
                # Replace with new handle using updated config
                new_handle = ChildServerHandle(config=new_by_id[sid])
                self._children[sid] = new_handle
                if new_by_id[sid].enabled:
                    await new_handle.start()
                restarted.append(sid)
            except Exception as exc:
                errors.append({"id": sid, "operation": "restart", "error": str(exc)})

        # 3. Remove old servers
        removed: list[str] = []
        for sid in diff["to_remove"]:
            try:
                await self.remove_server(sid)
                removed.append(sid)
            except Exception as exc:
                errors.append({"id": sid, "operation": "remove", "error": str(exc)})

        # Update internal config reference
        self._config = new_config

        return {
            "added": added,
            "restarted": restarted,
            "removed": removed,
            "unchanged": diff["unchanged"],
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # Health summary
    # ------------------------------------------------------------------

    def health_summary(self) -> dict[str, Any]:
        """Return a fleet-level health summary."""
        total = len(self._children)
        healthy = sum(1 for h in self._children.values() if h.state == ChildServerState.HEALTHY)
        degraded = sum(1 for h in self._children.values() if h.state == ChildServerState.DEGRADED)
        unhealthy = sum(
            1
            for h in self._children.values()
            if h.state in (ChildServerState.UNHEALTHY, ChildServerState.COOLDOWN)
        )
        return {
            "total": total,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "stopped": total - healthy - degraded - unhealthy,
        }
