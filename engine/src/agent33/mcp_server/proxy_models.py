"""Pydantic models for MCP proxy fleet configuration."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProxyServerAuth(BaseModel):
    """Authentication config for a proxied MCP server."""

    type: Literal["none", "env_bearer", "api_key", "vault"] = "none"
    env_var: str = ""
    vault_key: str = ""


class ProxyServerGovernance(BaseModel):
    """Governance policy for a proxied MCP server's tools."""

    policy: Literal["allow", "ask", "deny"] = "allow"
    allowed_tools: list[str] = Field(default_factory=lambda: ["*"])
    blocked_tools: list[str] = Field(default_factory=list)


class ProxyServerConfig(BaseModel):
    """Configuration for a single proxied MCP server."""

    id: str
    name: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    transport: Literal["stdio", "sse"] = "stdio"
    url: str = ""
    tool_prefix: str = ""
    enabled: bool = True
    health_check_interval_seconds: float = 60.0
    max_consecutive_failures: int = 3
    cooldown_seconds: float = 120.0
    auth: ProxyServerAuth = Field(default_factory=ProxyServerAuth)
    governance: ProxyServerGovernance = Field(default_factory=ProxyServerGovernance)

    def effective_prefix(self) -> str:
        """Return the tool prefix to use, falling back to the server id."""
        return self.tool_prefix or self.id


class ProxyFleetConfig(BaseModel):
    """Top-level configuration for the proxy fleet."""

    proxy_servers: list[ProxyServerConfig] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
