"""Tool registry for discovering and managing available tools."""

from __future__ import annotations

import importlib.metadata
import logging
from pathlib import Path
from typing import Any

import yaml

from agent33.tools.base import Tool, ToolContext, ToolResult
from agent33.tools.registry_entry import (
    ToolProvenance,
    ToolRegistryEntry,
    ToolStatus,
)
from agent33.tools.schema import get_tool_schema, validate_params

logger = logging.getLogger(__name__)


def _yaml_to_entry(data: dict[str, Any], source: str = "") -> ToolRegistryEntry:
    """Convert a parsed YAML dict into a *ToolRegistryEntry*."""
    provenance_raw = data.get("provenance", {})
    provenance = ToolProvenance(
        repo_url=provenance_raw.get("repo_url", ""),
        commit_or_tag=provenance_raw.get("commit_or_tag", ""),
        checksum=provenance_raw.get("checksum", ""),
        license=provenance_raw.get("license", ""),
    )

    name: str = data.get("name", "")
    status_raw = data.get("status", "active")
    try:
        status = ToolStatus(status_raw)
    except ValueError:
        logger.warning(
            "Invalid status value '%s' in %s, defaulting to 'active'.",
            status_raw,
            source or "<unknown>",
        )
        status = ToolStatus.ACTIVE

    return ToolRegistryEntry(
        tool_id=name,
        name=name,
        version=data.get("version", "0.0"),
        description=data.get("description", ""),
        owner=data.get("owner", ""),
        provenance=provenance,
        status=status,
    )


class ToolRegistry:
    """Central registry of available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._entries: dict[str, ToolRegistryEntry] = {}
        self._mcp_manager: Any = None

    # ------------------------------------------------------------------
    # Existing API (unchanged)
    # ------------------------------------------------------------------

    def register(self, tool: Tool) -> None:
        """Register a tool instance. Overwrites any existing tool with the same name."""
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def get(self, name: str) -> Tool | None:
        """Return the tool with the given name, or ``None``."""
        return self._tools.get(name)

    def list_all(self) -> list[Tool]:
        """Return all registered tools."""
        return list(self._tools.values())

    def discover_from_entrypoints(self, group: str = "agent33.tools") -> int:
        """Load tools advertised via setuptools entry points.

        Each entry point must resolve to a callable that returns a ``Tool``
        instance (or a ``Tool`` class that can be instantiated with no args).

        Returns the number of tools discovered.
        """
        count = 0
        eps = importlib.metadata.entry_points()
        # Python 3.12+ returns a SelectableGroups / dict; 3.9+ has .select()
        selected = eps.select(group=group) if hasattr(eps, "select") else eps.get(group, [])  # type: ignore[arg-type]
        for ep in selected:
            try:
                obj = ep.load()
                tool: Tool = obj() if callable(obj) and not isinstance(obj, Tool) else obj
                self.register(tool)
                count += 1
            except Exception:
                logger.exception("Failed to load tool entry point: %s", ep.name)
        return count

    async def discover_mcp_stdio_server(
        self, command: str, args: list[str], env: dict[str, str] | None = None
    ) -> int:
        """Connect to an MCP STDIO server and register its tools dynamically."""
        try:
            from agent33.tools.mcp_client import MCPClientManager
        except ImportError:
            logger.warning("MCP client not available (mcp package missing)")
            return 0

        if self._mcp_manager is None:
            self._mcp_manager = MCPClientManager()

        try:
            session = await self._mcp_manager.connect_stdio(command, args, env)
            tools = await self._mcp_manager.load_tools_from_session(session)
            count = 0
            for tool in tools:
                self.register(tool)
                count += 1
            logger.info("Discovered %d tools from MCP STDIO server: %s", count, command)
            return count
        except Exception:
            logger.error(
                "Failed to discover tools from MCP STDIO server: %s", command, exc_info=True
            )
            return 0

    async def discover_mcp_sse_server(self, url: str) -> int:
        """Connect to an MCP SSE server and register its tools dynamically."""
        try:
            from agent33.tools.mcp_client import MCPClientManager
        except ImportError:
            logger.warning("MCP client not available (mcp package missing)")
            return 0

        if self._mcp_manager is None:
            self._mcp_manager = MCPClientManager()

        try:
            session = await self._mcp_manager.connect_sse(url)
            tools = await self._mcp_manager.load_tools_from_session(session)
            count = 0
            for tool in tools:
                self.register(tool)
                count += 1
            logger.info("Discovered %d tools from MCP SSE server: %s", count, url)
            return count
        except Exception:
            logger.error("Failed to discover tools from MCP SSE server: %s", url, exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Phase 12 – metadata & change-control API
    # ------------------------------------------------------------------

    def register_with_entry(self, tool: Tool, entry: ToolRegistryEntry) -> None:
        """Register a tool together with its Phase 12 metadata entry."""
        self._tools[tool.name] = tool
        self._entries[entry.name] = entry
        logger.info("Registered tool with entry: %s (v%s)", entry.name, entry.version)

    def get_entry(self, name: str) -> ToolRegistryEntry | None:
        """Return the metadata entry for *name*, or ``None``."""
        return self._entries.get(name)

    def list_entries(self) -> list[ToolRegistryEntry]:
        """Return all metadata entries."""
        return list(self._entries.values())

    def set_status(self, name: str, status: ToolStatus, message: str = "") -> bool:
        """Change the status of a registered entry.

        Returns ``True`` if the entry was found and updated, ``False`` otherwise.
        """
        entry = self._entries.get(name)
        if entry is None:
            return False
        self._entries[name] = entry.model_copy(
            update={"status": status, "deprecation_message": message},
        )
        logger.info("Tool %s status → %s", name, status.value)
        return True

    async def validated_execute(
        self,
        name: str,
        params: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Validate params against the tool's schema, then execute.

        If the tool has a declared JSON Schema (via the tool itself or
        its registry entry), parameters are validated before execution.
        Invalid parameters return a ``ToolResult.fail`` without calling
        the tool.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult.fail(f"Tool '{name}' not found in registry")

        entry = self._entries.get(name)
        schema = get_tool_schema(tool, entry)

        if schema:
            result = validate_params(params, schema)
            if not result.valid:
                return ToolResult.fail(f"Parameter validation failed: {'; '.join(result.errors)}")

        return await tool.execute(params, context)

    def load_definitions(self, definitions_dir: str) -> int:
        """Load YAML tool definitions from *definitions_dir*.

        Each ``.yml`` / ``.yaml`` file is parsed into a
        :class:`ToolRegistryEntry` and stored.  Files that fail to parse are
        logged and skipped.

        Returns the number of entries successfully loaded.
        """
        dir_path = Path(definitions_dir)
        if not dir_path.is_dir():
            logger.warning("Definitions directory does not exist: %s", definitions_dir)
            return 0

        count = 0
        for yml_file in sorted(dir_path.iterdir()):
            if yml_file.suffix not in {".yml", ".yaml"}:
                continue
            try:
                data = yaml.safe_load(yml_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "name" not in data:
                    logger.warning("Skipping invalid definition: %s", yml_file.name)
                    continue
                entry = _yaml_to_entry(data, source=str(yml_file))
                self._entries[entry.name] = entry
                count += 1
                logger.debug("Loaded definition: %s from %s", entry.name, yml_file.name)
            except yaml.YAMLError:
                logger.exception("Failed to parse YAML definition: %s", yml_file.name)
            except Exception:
                logger.exception("Failed to load definition: %s", yml_file.name)
        return count
