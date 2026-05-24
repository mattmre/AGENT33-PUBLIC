"""Tool registry for discovering and managing available tools."""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from agent33.tools.base import Tool, ToolContext, ToolResult
from agent33.tools.registry_entry import (
    ToolApproval,
    ToolProvenance,
    ToolRegistryEntry,
    ToolScope,
    ToolStatus,
)
from agent33.tools.schema import get_tool_schema, validate_params

logger = logging.getLogger(__name__)


def _as_string_list(value: Any) -> list[str]:
    """Normalize YAML scalar/list values to a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _parse_date(value: Any, *, source: str, field_name: str) -> date | None:
    """Parse an ISO date field from YAML metadata."""
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            logger.warning(
                "Invalid %s date '%s' in %s; ignoring.",
                field_name,
                value,
                source or "<unknown>",
            )
            return None
    logger.warning(
        "Invalid %s date value in %s; expected ISO date string.",
        field_name,
        source or "<unknown>",
    )
    return None


def _parameters_to_json_schema(parameters: Any) -> dict[str, Any]:
    """Convert the shipped YAML parameter shorthand to JSON Schema."""
    if not isinstance(parameters, dict):
        return {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    passthrough_keys = {
        "default",
        "description",
        "enum",
        "format",
        "items",
        "maximum",
        "minimum",
        "properties",
        "type",
    }

    for name, raw_spec in parameters.items():
        if not isinstance(name, str) or not isinstance(raw_spec, dict):
            continue
        property_schema = {
            key: value
            for key, value in raw_spec.items()
            if key in passthrough_keys and value is not None
        }
        property_schema.setdefault("type", "string")
        properties[name] = property_schema
        if raw_spec.get("required") is True:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _scope_from_governance(governance: dict[str, Any]) -> ToolScope:
    """Map raw YAML governance metadata into the normalized scope summary."""
    commands = _as_string_list(governance.get("command_allowlist"))
    endpoints = _as_string_list(governance.get("domain_allowlist"))
    endpoints.extend(_as_string_list(governance.get("endpoints")))

    filesystem = _as_string_list(governance.get("path_allowlist"))
    filesystem.extend(_as_string_list(governance.get("filesystem")))

    data_access = str(governance.get("data_access", "none")).lower()
    if data_access not in {"read", "write", "none"}:
        data_access = "none"
    if governance.get("write_operation") is True:
        data_access = "write"

    return ToolScope(
        commands=commands,
        endpoints=endpoints,
        data_access=data_access,  # type: ignore[arg-type]
        network=bool(endpoints or governance.get("network") is True),
        filesystem=filesystem,
    )


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

    governance_raw = data.get("governance", {})
    governance = governance_raw if isinstance(governance_raw, dict) else {}
    parameters_schema_raw = data.get("parameters_schema")
    parameters_schema = (
        parameters_schema_raw
        if isinstance(parameters_schema_raw, dict)
        else _parameters_to_json_schema(data.get("parameters"))
    )
    result_schema_raw = data.get("result_schema", {})
    result_schema = result_schema_raw if isinstance(result_schema_raw, dict) else {}
    approval_raw = data.get("approval", {})
    approval_data = approval_raw if isinstance(approval_raw, dict) else {}
    approval = ToolApproval(
        approver=str(approval_data.get("approver", "")),
        approved_date=_parse_date(
            approval_data.get("approved_date"),
            source=source,
            field_name="approval.approved_date",
        ),
        evidence=str(approval_data.get("evidence", "")),
    )

    return ToolRegistryEntry(
        tool_id=str(data.get("tool_id") or name),
        name=name,
        version=data.get("version", "0.0"),
        description=data.get("description", ""),
        owner=data.get("owner", ""),
        provenance=provenance,
        scope=_scope_from_governance(governance),
        approval=approval,
        status=status,
        last_review=_parse_date(data.get("last_review"), source=source, field_name="last_review"),
        next_review=_parse_date(data.get("next_review"), source=source, field_name="next_review"),
        deprecation_message=str(data.get("deprecation_message", "")),
        tags=_as_string_list(data.get("tags")),
        governance=governance,
        parameters_schema=parameters_schema,
        result_schema=result_schema,
    )


def _intersect_or_registry_values(
    context_values: list[str],
    registry_values: list[str],
) -> list[str]:
    """Use registry values when context is unset, otherwise keep the intersection."""
    if not registry_values:
        return context_values
    if not context_values:
        return registry_values
    registry_set = set(registry_values)
    return [value for value in context_values if value in registry_set]


def _dedupe(values: list[str]) -> list[str]:
    """Return values without duplicates while preserving declaration order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


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
        self.load_default_definitions()
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

    def load_default_definitions(self) -> int:
        """Load the packaged YAML tool definitions shipped with the engine."""
        definitions_dir = Path(__file__).resolve().parents[3] / "tool-definitions"
        return self.load_definitions(str(definitions_dir))

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

    def default_context_allowlists(self) -> dict[str, list[str]]:
        """Return non-empty allowlists loaded from tool definition metadata.

        Route-level ``ToolContext`` builders use these values so governance
        checks see the same default runtime policy that registry execution
        applies from packaged tool definitions. Empty declared allowlists are
        intentionally omitted so shell/file/web builtins still fail closed
        unless the route supplies an explicit runtime allowlist.
        """
        command_allowlist: list[str] = []
        path_allowlist: list[str] = []
        domain_allowlist: list[str] = []

        for entry in self._entries.values():
            governance = entry.governance
            if "command_allowlist" in governance:
                command_allowlist.extend(entry.scope.commands)
            if "path_allowlist" in governance:
                path_allowlist.extend(entry.scope.filesystem)
            if "domain_allowlist" in governance or "endpoints" in governance:
                domain_allowlist.extend(entry.scope.endpoints)

        return {
            "command_allowlist": _dedupe(command_allowlist),
            "path_allowlist": _dedupe(path_allowlist),
            "domain_allowlist": _dedupe(domain_allowlist),
        }

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

        scoped_context_result = self.context_for_tool(name, context)
        if isinstance(scoped_context_result, ToolResult):
            return scoped_context_result

        return await tool.execute(params, scoped_context_result)

    def context_for_tool(
        self,
        name: str,
        context: ToolContext,
    ) -> ToolContext | ToolResult:
        """Apply registry-declared allowlists to execution context.

        A YAML entry that declares an allowlist owns the runtime boundary for
        that axis. Empty declared allowlists fail closed unless the caller
        supplied an explicit runtime allowlist. If both caller and registry
        policy provide values, the effective values are their intersection.
        """
        entry = self._entries.get(name)
        if entry is None:
            return context

        governance = entry.governance
        command_declared = "command_allowlist" in governance
        path_declared = "path_allowlist" in governance
        domain_declared = "domain_allowlist" in governance or "endpoints" in governance

        command_allowlist = context.command_allowlist
        path_allowlist = context.path_allowlist
        domain_allowlist = context.domain_allowlist

        if command_declared:
            if not entry.scope.commands:
                if not context.command_allowlist:
                    return ToolResult.fail(
                        f"Tool '{name}' registry command allowlist is empty; denied by default"
                    )
                command_allowlist = context.command_allowlist
            else:
                command_allowlist = _intersect_or_registry_values(
                    context.command_allowlist,
                    entry.scope.commands,
                )
            if not command_allowlist:
                return ToolResult.fail(
                    f"Tool '{name}' has no command allowed by both context and registry policy"
                )

        if path_declared:
            if not entry.scope.filesystem:
                if not context.path_allowlist:
                    return ToolResult.fail(
                        f"Tool '{name}' registry path allowlist is empty; denied by default"
                    )
                path_allowlist = context.path_allowlist
            else:
                path_allowlist = _intersect_or_registry_values(
                    context.path_allowlist,
                    entry.scope.filesystem,
                )
            if not path_allowlist:
                return ToolResult.fail(
                    f"Tool '{name}' has no path allowed by both context and registry policy"
                )

        if domain_declared:
            if not entry.scope.endpoints:
                if not context.domain_allowlist:
                    return ToolResult.fail(
                        f"Tool '{name}' registry domain allowlist is empty; denied by default"
                    )
                domain_allowlist = context.domain_allowlist
            else:
                domain_allowlist = _intersect_or_registry_values(
                    context.domain_allowlist,
                    entry.scope.endpoints,
                )
            if not domain_allowlist:
                return ToolResult.fail(
                    f"Tool '{name}' has no domain allowed by both context and registry policy"
                )

        if (
            command_allowlist == context.command_allowlist
            and path_allowlist == context.path_allowlist
            and domain_allowlist == context.domain_allowlist
        ):
            return context

        return replace(
            context,
            command_allowlist=command_allowlist,
            path_allowlist=path_allowlist,
            domain_allowlist=domain_allowlist,
        )

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
