"""Session-scoped tool activation and visibility helpers for dynamic discovery."""

from __future__ import annotations

import json
import threading
from typing import TYPE_CHECKING, Any

from agent33.tools.base import ToolContext, ToolResult

if TYPE_CHECKING:
    from agent33.discovery.service import DiscoveryService
    from agent33.tools.base import Tool
    from agent33.tools.registry import ToolRegistry


DISCOVER_TOOLS_TOOL_NAME = "discover_tools"
DISCOVER_TOOLS_TOOL_VERSION = "0.1.0"


class ToolActivationManager:
    """Track active tools per tenant/session for dynamic visibility mode."""

    def __init__(self) -> None:
        self._active_tools: dict[tuple[str, str], list[str]] = {}
        self._lock = threading.Lock()

    def _key(
        self,
        *,
        tenant_id: str = "",
        session_id: str = "",
        requested_by: str = "",
    ) -> tuple[str, str]:
        scope_key = tenant_id.strip()
        if not scope_key:
            requester = requested_by.strip()
            scope_key = f"user:{requester}" if requester else "anonymous"
        return (scope_key, session_id)

    def activate_tools(
        self,
        tool_names: list[str],
        *,
        tenant_id: str = "",
        session_id: str = "",
        requested_by: str = "",
    ) -> list[str]:
        """Activate tools for the given tenant/session and return newly activated names."""
        if not session_id:
            return []

        key = self._key(
            tenant_id=tenant_id,
            session_id=session_id,
            requested_by=requested_by,
        )
        with self._lock:
            existing = list(self._active_tools.get(key, []))
            seen = set(existing)
            activated: list[str] = []

            for tool_name in tool_names:
                normalized = tool_name.strip()
                if not normalized or normalized in seen:
                    continue
                existing.append(normalized)
                activated.append(normalized)
                seen.add(normalized)

            if activated:
                self._active_tools[key] = existing

            return activated

    def list_active_tools(
        self,
        *,
        tenant_id: str = "",
        session_id: str = "",
        requested_by: str = "",
    ) -> list[str]:
        """Return active tools for the given tenant/session."""
        if not session_id:
            return []
        with self._lock:
            return list(
                self._active_tools.get(
                    self._key(
                        tenant_id=tenant_id,
                        session_id=session_id,
                        requested_by=requested_by,
                    ),
                    [],
                )
            )


class SessionToolRegistryView:
    """Visibility-filtering view over the shared tool registry."""

    def __init__(
        self,
        base_registry: ToolRegistry,
        *,
        mode: str = "legacy",
        activation_manager: ToolActivationManager | None = None,
        context: ToolContext | None = None,
    ) -> None:
        self._base_registry = base_registry
        self._mode = mode
        self._activation_manager = activation_manager
        self._context = context or ToolContext()

    def get(self, name: str) -> Tool | None:
        """Return a tool by exact name from the underlying registry."""
        return self._base_registry.get(name)

    def get_entry(self, name: str) -> Any:
        """Return registry metadata for a tool."""
        return self._base_registry.get_entry(name)

    async def validated_execute(
        self,
        name: str,
        params: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute by exact name using the underlying registry without visibility blocking."""
        return await self._base_registry.validated_execute(name, params, context)

    def list_all(self) -> list[Tool]:
        """Return only tools visible for the current context."""
        tools = self._base_registry.list_all()
        if not self._should_narrow_visibility():
            return [tool for tool in tools if tool.name != DISCOVER_TOOLS_TOOL_NAME]

        assert self._activation_manager is not None
        active_names = set(
            self._activation_manager.list_active_tools(
                tenant_id=self._context.tenant_id,
                session_id=self._context.session_id,
                requested_by=self._context.requested_by,
            )
        )
        visible_names = {DISCOVER_TOOLS_TOOL_NAME, *active_names}

        discover_tool: Tool | None = None
        visible_tools: list[Tool] = []
        for tool in tools:
            if self._is_blocked(tool.name):
                continue
            if tool.name == DISCOVER_TOOLS_TOOL_NAME:
                discover_tool = tool
                continue
            if tool.name in visible_names:
                visible_tools.append(tool)

        return ([discover_tool] if discover_tool is not None else []) + visible_tools

    def _should_narrow_visibility(self) -> bool:
        return (
            self._mode == "dynamic"
            and self._activation_manager is not None
            and bool(self._context.session_id.strip())
        )

    def _is_blocked(self, tool_name: str) -> bool:
        entry = self._base_registry.get_entry(tool_name)
        return getattr(getattr(entry, "status", None), "value", "") == "blocked"


class DiscoverToolsTool:
    """Runtime tool that discovers and activates relevant tools for the current session."""

    def __init__(
        self,
        *,
        discovery_service: DiscoveryService,
        activation_manager: ToolActivationManager | None = None,
        mode: str = "legacy",
        default_limit: int = 5,
        default_activation_limit: int = 3,
    ) -> None:
        self._discovery_service = discovery_service
        self._activation_manager = activation_manager
        self._mode = mode
        self._default_limit = default_limit
        self._default_activation_limit = default_activation_limit

    @property
    def name(self) -> str:
        return DISCOVER_TOOLS_TOOL_NAME

    @property
    def description(self) -> str:
        return "Discover relevant tools for the current task and activate them for this session."

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Task or search query describing the tool you need.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches to return.",
                    "default": self._default_limit,
                    "minimum": 1,
                },
                "activate": {
                    "type": "boolean",
                    "description": (
                        "Activate the matched tools for this session when dynamic mode is on."
                    ),
                    "default": True,
                },
                "activation_limit": {
                    "type": "integer",
                    "description": "Maximum number of matched tools to activate.",
                    "default": self._default_activation_limit,
                    "minimum": 1,
                },
            },
            "required": ["query"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Discover relevant tools and optionally activate them for the current session."""
        query = str(params.get("query", "")).strip()
        if not query:
            return ToolResult.fail("No query provided")

        limit = max(1, int(params.get("limit", self._default_limit)))
        activate = bool(params.get("activate", True))
        activation_limit = max(
            1, int(params.get("activation_limit", self._default_activation_limit))
        )

        matches = self._discovery_service.discover_tools(query, limit=limit)
        activated: list[str] = []
        activation_state = "not_requested"

        if activate and self._mode == "dynamic" and self._activation_manager is not None:
            if context.session_id:
                activation_candidates = [
                    match.name for match in matches if match.name != DISCOVER_TOOLS_TOOL_NAME
                ]
                activated = self._activation_manager.activate_tools(
                    activation_candidates[:activation_limit],
                    tenant_id=context.tenant_id,
                    session_id=context.session_id,
                    requested_by=context.requested_by,
                )
                activation_state = "activated"
            else:
                activation_state = "skipped_no_session"
        elif activate and self._mode == "dynamic":
            activation_state = "skipped_unavailable"
        elif activate:
            activation_state = "legacy_mode"

        payload = {
            "query": query,
            "matches": [match.model_dump(mode="json") for match in matches],
            "activated": activated,
            "activation_state": activation_state,
        }
        return ToolResult.ok(json.dumps(payload))
