"""Tests for MCP proxy fleet configuration models (Phase 45)."""

from __future__ import annotations

from agent33.mcp_server.proxy_models import (
    ProxyFleetConfig,
    ProxyServerAuth,
    ProxyServerConfig,
    ProxyServerGovernance,
)


class TestProxyServerConfig:
    """ProxyServerConfig: validation, defaults, effective prefix."""

    def test_minimal_config(self) -> None:
        cfg = ProxyServerConfig(id="test")
        assert cfg.id == "test"
        assert cfg.transport == "stdio"
        assert cfg.enabled is True
        assert cfg.tool_prefix == ""
        assert cfg.max_consecutive_failures == 3

    def test_full_config(self) -> None:
        cfg = ProxyServerConfig(
            id="elevenlabs",
            name="ElevenLabs MCP",
            command="npx",
            args=["-y", "@anthropic/elevenlabs-mcp-server"],
            env={"ELEVENLABS_API_KEY": "${ELEVENLABS_API_KEY}"},
            transport="stdio",
            tool_prefix="el",
            enabled=True,
            health_check_interval_seconds=30.0,
            max_consecutive_failures=5,
            cooldown_seconds=300.0,
            auth=ProxyServerAuth(type="env_bearer", env_var="ELEVENLABS_API_KEY"),
            governance=ProxyServerGovernance(
                policy="ask",
                allowed_tools=["*"],
                blocked_tools=["dangerous_tool"],
            ),
        )
        assert cfg.name == "ElevenLabs MCP"
        assert cfg.args == ["-y", "@anthropic/elevenlabs-mcp-server"]
        assert cfg.auth.type == "env_bearer"
        assert cfg.governance.policy == "ask"
        assert "dangerous_tool" in cfg.governance.blocked_tools

    def test_effective_prefix_uses_tool_prefix(self) -> None:
        cfg = ProxyServerConfig(id="server1", tool_prefix="my_prefix")
        assert cfg.effective_prefix() == "my_prefix"

    def test_effective_prefix_falls_back_to_id(self) -> None:
        cfg = ProxyServerConfig(id="server1", tool_prefix="")
        assert cfg.effective_prefix() == "server1"

    def test_sse_transport_with_url(self) -> None:
        cfg = ProxyServerConfig(
            id="remote",
            transport="sse",
            url="http://localhost:9000/mcp/sse",
        )
        assert cfg.transport == "sse"
        assert cfg.url == "http://localhost:9000/mcp/sse"


class TestProxyServerAuth:
    """Auth config validation."""

    def test_default_auth(self) -> None:
        auth = ProxyServerAuth()
        assert auth.type == "none"
        assert auth.env_var == ""

    def test_env_bearer_auth(self) -> None:
        auth = ProxyServerAuth(type="env_bearer", env_var="MY_API_KEY")
        assert auth.type == "env_bearer"
        assert auth.env_var == "MY_API_KEY"

    def test_vault_auth(self) -> None:
        auth = ProxyServerAuth(type="vault", vault_key="secret/mcp/key")
        assert auth.type == "vault"


class TestProxyServerGovernance:
    """Governance policy validation."""

    def test_default_governance(self) -> None:
        gov = ProxyServerGovernance()
        assert gov.policy == "allow"
        assert gov.allowed_tools == ["*"]
        assert gov.blocked_tools == []

    def test_deny_policy(self) -> None:
        gov = ProxyServerGovernance(policy="deny")
        assert gov.policy == "deny"

    def test_selective_allowlist(self) -> None:
        gov = ProxyServerGovernance(
            allowed_tools=["read_file", "list_directory"],
            blocked_tools=["write_file"],
        )
        assert "read_file" in gov.allowed_tools
        assert "write_file" in gov.blocked_tools


class TestProxyFleetConfig:
    """Fleet-level configuration."""

    def test_empty_fleet(self) -> None:
        cfg = ProxyFleetConfig()
        assert cfg.proxy_servers == []
        assert cfg.defaults == {}

    def test_fleet_with_servers(self) -> None:
        cfg = ProxyFleetConfig(
            proxy_servers=[
                ProxyServerConfig(id="server-a"),
                ProxyServerConfig(id="server-b"),
            ],
            defaults={"transport": "stdio"},
        )
        assert len(cfg.proxy_servers) == 2
        assert cfg.proxy_servers[0].id == "server-a"

    def test_fleet_serialization_roundtrip(self) -> None:
        cfg = ProxyFleetConfig(
            proxy_servers=[
                ProxyServerConfig(
                    id="fs",
                    command="npx",
                    args=["-y", "@modelcontextprotocol/server-filesystem"],
                    tool_prefix="fs",
                )
            ]
        )
        data = cfg.model_dump()
        restored = ProxyFleetConfig.model_validate(data)
        assert restored.proxy_servers[0].id == "fs"
        assert restored.proxy_servers[0].tool_prefix == "fs"
