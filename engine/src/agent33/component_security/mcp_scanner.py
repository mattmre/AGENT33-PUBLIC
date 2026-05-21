"""MCP security server integration for component security scanning.

Connects enterprise MCP security servers (Semgrep, Trivy, Snyk) as pluggable
scan providers. Uses the existing MCPClientManager from agent33.tools.mcp_client.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from agent33.component_security.models import (
    FindingCategory,
    FindingSeverity,
    SecurityFinding,
)

logger = structlog.get_logger()


class MCPTransport(StrEnum):
    """Supported MCP transport types."""

    STDIO = "stdio"
    SSE = "sse"


class MCPServerConfig(BaseModel):
    """Configuration for a registered MCP security server."""

    name: str
    transport: MCPTransport
    command: str = ""  # For STDIO transport
    args: list[str] = Field(default_factory=list)  # For STDIO transport
    url: str = ""  # For SSE transport
    env: dict[str, str] = Field(default_factory=dict)
    scan_tool_name: str = "scan"  # Name of the scan tool on the MCP server
    timeout_seconds: int = Field(default=300, ge=30, le=3600)


# Pre-registered server configs for known enterprise security servers
KNOWN_SERVERS: dict[str, MCPServerConfig] = {
    "semgrep": MCPServerConfig(
        name="semgrep",
        transport=MCPTransport.STDIO,
        command="npx",
        args=["-y", "@semgrep/mcp"],
        scan_tool_name="scan",
    ),
    "trivy": MCPServerConfig(
        name="trivy",
        transport=MCPTransport.STDIO,
        command="trivy",
        args=["mcp", "--server"],
        scan_tool_name="scan",
    ),
}


class MCPSecurityScanner:
    """Manages MCP security server connections and scan execution.

    Provides registration, discovery, and invocation of MCP-based security
    scanning tools. Each registered server can be invoked to scan a target
    and produce SecurityFindings.
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerConfig] = {}

    def register_server(
        self,
        name: str,
        transport: str,
        config: dict[str, Any],
    ) -> MCPServerConfig:
        """Register an MCP security server.

        Args:
            name: Unique name for the server.
            transport: Transport type ('stdio' or 'sse').
            config: Server configuration dict (command, args, url, env, etc.).

        Returns:
            The registered server configuration.

        Raises:
            ValueError: If transport is invalid or required fields are missing.
        """
        try:
            transport_enum = MCPTransport(transport)
        except ValueError as exc:
            raise ValueError(
                f"Invalid transport '{transport}'. Must be 'stdio' or 'sse'."
            ) from exc

        if transport_enum == MCPTransport.STDIO and not config.get("command"):
            raise ValueError("STDIO transport requires 'command' in config.")
        if transport_enum == MCPTransport.SSE and not config.get("url"):
            raise ValueError("SSE transport requires 'url' in config.")

        server_config = MCPServerConfig(
            name=name,
            transport=transport_enum,
            command=config.get("command", ""),
            args=config.get("args", []),
            url=config.get("url", ""),
            env=config.get("env", {}),
            scan_tool_name=config.get("scan_tool_name", "scan"),
            timeout_seconds=config.get("timeout_seconds", 300),
        )
        self._servers[name] = server_config
        logger.info("mcp_security_server_registered", name=name, transport=transport)
        return server_config

    def unregister_server(self, name: str) -> bool:
        """Remove a registered MCP security server.

        Returns True if the server was found and removed, False otherwise.
        """
        if name in self._servers:
            del self._servers[name]
            logger.info("mcp_security_server_unregistered", name=name)
            return True
        return False

    def list_servers(self) -> list[MCPServerConfig]:
        """Return all registered server configurations."""
        return list(self._servers.values())

    def get_server(self, name: str) -> MCPServerConfig | None:
        """Get a registered server by name."""
        return self._servers.get(name)

    async def scan(
        self,
        server_name: str,
        target: str,
        run_id: str,
    ) -> list[SecurityFinding]:
        """Invoke a scan tool on a registered MCP server.

        This method connects to the MCP server, invokes its scan tool,
        and parses the response into SecurityFindings.

        Args:
            server_name: Name of the registered MCP server.
            target: Path or URI of the scan target.
            run_id: ID of the security run to associate findings with.

        Returns:
            List of SecurityFindings produced by the MCP server.

        Raises:
            ValueError: If the server is not registered.
        """
        server = self._servers.get(server_name)
        if server is None:
            raise ValueError(f"MCP security server not registered: {server_name}")

        try:
            from agent33.tools.mcp_client import MCPClientManager

            manager = MCPClientManager()
            try:
                if server.transport == MCPTransport.STDIO:
                    session = await manager.connect_stdio(
                        command=server.command,
                        args=server.args,
                        env=server.env or None,
                    )
                else:
                    session = await manager.connect_sse(url=server.url)

                result = await manager.call_tool(
                    session=session,
                    tool_name=server.scan_tool_name,
                    arguments={"target": target},
                    connector_name=f"mcp:{server.name}",
                    timeout_seconds=float(server.timeout_seconds),
                )

                return self._parse_scan_result(
                    result=result,
                    server_name=server_name,
                    run_id=run_id,
                )
            finally:
                await manager.close_all()

        except Exception as exc:
            logger.warning(
                "mcp_security_scan_failed",
                server=server_name,
                target=target,
                exc_info=True,
            )
            return [
                SecurityFinding(
                    run_id=run_id,
                    severity=FindingSeverity.HIGH,
                    category=FindingCategory.CODE_QUALITY,
                    title=f"{server_name} scan execution failed",
                    description=(str(exc) or exc.__class__.__name__)[:500],
                    tool=server_name,
                )
            ]

    def _parse_scan_result(
        self,
        result: Any,
        server_name: str,
        run_id: str,
    ) -> list[SecurityFinding]:
        """Parse MCP tool call result into SecurityFindings."""
        findings: list[SecurityFinding] = []

        # Extract text content from MCP result
        raw_text = ""
        for item in getattr(result, "content", []):
            if hasattr(item, "text"):
                raw_text += item.text

        if not raw_text.strip():
            return findings

        # Try to parse as JSON (SARIF or findings array)
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            # Non-JSON output: create a single informational finding
            findings.append(
                SecurityFinding(
                    run_id=run_id,
                    severity=FindingSeverity.INFO,
                    category=FindingCategory.CODE_QUALITY,
                    title=f"{server_name} scan output",
                    description=raw_text[:500],
                    tool=server_name,
                )
            )
            return findings

        # If it looks like SARIF, use the SARIF converter
        if isinstance(data, dict) and "runs" in data:
            try:
                from agent33.component_security.sarif import SARIFConverter

                return SARIFConverter.sarif_to_findings(data, run_id=run_id)
            except Exception:
                logger.warning(
                    "mcp_sarif_parse_failed",
                    server=server_name,
                    exc_info=True,
                )

        # If it's a list of finding-like objects, parse them directly
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    findings.append(
                        SecurityFinding(
                            run_id=run_id,
                            severity=self._map_severity(item.get("severity", "info")),
                            category=self._map_category(item.get("category", "code-quality")),
                            title=item.get("title", f"{server_name} finding"),
                            description=item.get("description", item.get("message", "")),
                            tool=server_name,
                            file_path=item.get("file", item.get("path", "")),
                            line_number=item.get("line"),
                            remediation=item.get("remediation", ""),
                            cwe_id=item.get("cwe_id", ""),
                        )
                    )

        return findings

    @staticmethod
    def _map_severity(raw: str) -> FindingSeverity:
        """Map raw severity string to FindingSeverity."""
        normalized = raw.lower().strip()
        for sev in FindingSeverity:
            if sev.value == normalized:
                return sev
        if normalized in {"error", "err"}:
            return FindingSeverity.HIGH
        if normalized in {"warning", "warn"}:
            return FindingSeverity.MEDIUM
        return FindingSeverity.INFO

    @staticmethod
    def _map_category(raw: str) -> FindingCategory:
        """Map raw category string to FindingCategory."""
        normalized = raw.lower().strip()
        for cat in FindingCategory:
            if cat.value == normalized:
                return cat
        return FindingCategory.CODE_QUALITY
