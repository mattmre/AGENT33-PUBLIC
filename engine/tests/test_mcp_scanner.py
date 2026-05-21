"""Tests for MCP security server integration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent33.component_security.mcp_scanner import (
    KNOWN_SERVERS,
    MCPSecurityScanner,
    MCPTransport,
)
from agent33.component_security.models import (
    FindingCategory,
    FindingSeverity,
)


class TestMCPServerRegistration:
    def test_register_stdio_server(self) -> None:
        scanner = MCPSecurityScanner()
        config = scanner.register_server(
            "test-scanner",
            "stdio",
            {"command": "scanner", "args": ["--scan"]},
        )
        assert config.name == "test-scanner"
        assert config.transport == MCPTransport.STDIO
        assert config.command == "scanner"
        assert config.args == ["--scan"]

    def test_register_sse_server(self) -> None:
        scanner = MCPSecurityScanner()
        config = scanner.register_server(
            "remote-scanner",
            "sse",
            {"url": "https://scanner.example.com/mcp"},
        )
        assert config.name == "remote-scanner"
        assert config.transport == MCPTransport.SSE
        assert config.url == "https://scanner.example.com/mcp"

    def test_register_invalid_transport(self) -> None:
        scanner = MCPSecurityScanner()
        with pytest.raises(ValueError, match="Invalid transport"):
            scanner.register_server("bad", "websocket", {})

    def test_register_stdio_missing_command(self) -> None:
        scanner = MCPSecurityScanner()
        with pytest.raises(ValueError, match="requires 'command'"):
            scanner.register_server("bad", "stdio", {})

    def test_register_sse_missing_url(self) -> None:
        scanner = MCPSecurityScanner()
        with pytest.raises(ValueError, match="requires 'url'"):
            scanner.register_server("bad", "sse", {})

    def test_list_servers(self) -> None:
        scanner = MCPSecurityScanner()
        scanner.register_server("a", "stdio", {"command": "a"})
        scanner.register_server("b", "sse", {"url": "https://b.example.com"})
        servers = scanner.list_servers()
        assert len(servers) == 2
        names = {s.name for s in servers}
        assert names == {"a", "b"}

    def test_get_server(self) -> None:
        scanner = MCPSecurityScanner()
        scanner.register_server("test", "stdio", {"command": "test"})
        assert scanner.get_server("test") is not None
        assert scanner.get_server("nonexistent") is None

    def test_unregister_server(self) -> None:
        scanner = MCPSecurityScanner()
        scanner.register_server("test", "stdio", {"command": "test"})
        assert scanner.unregister_server("test") is True
        assert scanner.unregister_server("test") is False
        assert scanner.list_servers() == []

    def test_unregister_nonexistent(self) -> None:
        scanner = MCPSecurityScanner()
        assert scanner.unregister_server("nope") is False


class TestKnownServers:
    def test_semgrep_config(self) -> None:
        config = KNOWN_SERVERS["semgrep"]
        assert config.transport == MCPTransport.STDIO
        assert config.command == "npx"

    def test_trivy_config(self) -> None:
        config = KNOWN_SERVERS["trivy"]
        assert config.transport == MCPTransport.STDIO
        assert config.command == "trivy"


class TestMCPScanParsing:
    def test_parse_json_findings_list(self) -> None:
        scanner = MCPSecurityScanner()
        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = json.dumps(
            [
                {
                    "title": "SQL Injection",
                    "severity": "high",
                    "category": "injection-risk",
                    "description": "Found SQL injection vulnerability",
                    "file": "app.py",
                    "line": 42,
                    "remediation": "Use parameterized queries",
                }
            ]
        )
        mock_result.content = [mock_content]

        findings = scanner._parse_scan_result(
            result=mock_result,
            server_name="test-mcp",
            run_id="secrun-mcp-1",
        )
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.HIGH
        assert findings[0].category == FindingCategory.INJECTION_RISK
        assert findings[0].title == "SQL Injection"
        assert findings[0].file_path == "app.py"
        assert findings[0].line_number == 42
        assert findings[0].tool == "test-mcp"

    def test_parse_empty_result(self) -> None:
        scanner = MCPSecurityScanner()
        mock_result = MagicMock()
        mock_result.content = []
        findings = scanner._parse_scan_result(
            result=mock_result,
            server_name="test",
            run_id="secrun-empty",
        )
        assert findings == []

    def test_parse_non_json_result(self) -> None:
        scanner = MCPSecurityScanner()
        mock_result = MagicMock()
        mock_content = MagicMock()
        mock_content.text = "Some plain text scan output"
        mock_result.content = [mock_content]
        findings = scanner._parse_scan_result(
            result=mock_result,
            server_name="text-scanner",
            run_id="secrun-text",
        )
        assert len(findings) == 1
        assert findings[0].severity == FindingSeverity.INFO
        assert findings[0].tool == "text-scanner"

    def test_severity_mapping(self) -> None:
        scanner = MCPSecurityScanner()
        assert scanner._map_severity("critical") == FindingSeverity.CRITICAL
        assert scanner._map_severity("HIGH") == FindingSeverity.HIGH
        assert scanner._map_severity("error") == FindingSeverity.HIGH
        assert scanner._map_severity("warning") == FindingSeverity.MEDIUM
        assert scanner._map_severity("unknown") == FindingSeverity.INFO

    def test_category_mapping(self) -> None:
        scanner = MCPSecurityScanner()
        assert scanner._map_category("injection-risk") == FindingCategory.INJECTION_RISK
        assert scanner._map_category("unknown") == FindingCategory.CODE_QUALITY


class TestMCPScanExecution:
    @pytest.mark.asyncio
    async def test_scan_unregistered_server(self) -> None:
        scanner = MCPSecurityScanner()
        with pytest.raises(ValueError, match="not registered"):
            await scanner.scan("nonexistent", "/path", "secrun-1")

    @pytest.mark.asyncio
    async def test_scan_connection_failure_returns_failure_finding(self) -> None:
        scanner = MCPSecurityScanner()
        scanner.register_server("failing", "stdio", {"command": "nonexistent-cmd"})

        findings = await scanner.scan("failing", "/path", "secrun-fail")
        assert len(findings) == 1
        assert findings[0].run_id == "secrun-fail"
        assert findings[0].severity == FindingSeverity.HIGH
        assert findings[0].category == FindingCategory.CODE_QUALITY
        assert findings[0].tool == "failing"
        assert findings[0].title == "failing scan execution failed"

    @pytest.mark.asyncio
    async def test_scan_passes_server_timeout_to_mcp_manager(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("mcp")
        scanner = MCPSecurityScanner()
        scanner.register_server(
            "timeout-test",
            "stdio",
            {"command": "scanner", "timeout_seconds": 123},
        )
        captured: dict[str, float] = {}

        class _MockText:
            text = "[]"

        class _MockResult:
            content = [_MockText()]

        class _MockManager:
            async def connect_stdio(self, command, args, env=None):  # noqa: ANN001, ARG002
                return object()

            async def call_tool(self, *args, **kwargs):  # noqa: ANN002
                captured["timeout_seconds"] = kwargs["timeout_seconds"]
                return _MockResult()

            async def close_all(self):  # noqa: ANN201
                return None

        monkeypatch.setattr(
            "agent33.tools.mcp_client.MCPClientManager",
            _MockManager,
        )

        findings = await scanner.scan("timeout-test", "/path", "secrun-timeout")
        assert findings == []
        assert captured["timeout_seconds"] == 123.0


class TestMCPServerRoutes:
    """Test MCP server management API routes."""

    @pytest.fixture(autouse=True)
    def _reset_mcp_scanner(self) -> None:
        from agent33.api.routes.component_security import _mcp_scanner

        _mcp_scanner._servers.clear()
        yield  # type: ignore[misc]
        _mcp_scanner._servers.clear()

    def test_register_list_delete_lifecycle(self) -> None:
        from fastapi.testclient import TestClient

        from agent33.main import app
        from agent33.security.auth import create_access_token

        token = create_access_token(
            "mcp-test", scopes=["component-security:read", "component-security:write"]
        )
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        # Register
        response = client.post(
            "/v1/component-security/mcp-servers",
            json={
                "name": "test-scanner",
                "transport": "stdio",
                "config": {"command": "scanner", "args": ["--scan"]},
            },
        )
        assert response.status_code == 201
        assert response.json()["name"] == "test-scanner"

        # List
        response = client.get("/v1/component-security/mcp-servers")
        assert response.status_code == 200
        assert len(response.json()) == 1

        # Delete
        response = client.delete("/v1/component-security/mcp-servers/test-scanner")
        assert response.status_code == 200

        # Verify deleted
        response = client.get("/v1/component-security/mcp-servers")
        assert response.status_code == 200
        assert len(response.json()) == 0

        # Delete nonexistent
        response = client.delete("/v1/component-security/mcp-servers/nope")
        assert response.status_code == 404

    def test_register_invalid_transport(self) -> None:
        from fastapi.testclient import TestClient

        from agent33.main import app
        from agent33.security.auth import create_access_token

        token = create_access_token(
            "mcp-test", scopes=["component-security:read", "component-security:write"]
        )
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        response = client.post(
            "/v1/component-security/mcp-servers",
            json={"name": "bad", "transport": "websocket", "config": {}},
        )
        assert response.status_code == 400

    def test_register_missing_required_fields(self) -> None:
        from fastapi.testclient import TestClient

        from agent33.main import app
        from agent33.security.auth import create_access_token

        token = create_access_token("mcp-test", scopes=["component-security:write"])
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        # Missing name
        response = client.post(
            "/v1/component-security/mcp-servers",
            json={"transport": "stdio", "config": {"command": "test"}},
        )
        assert response.status_code == 400

        # Missing transport
        response = client.post(
            "/v1/component-security/mcp-servers",
            json={"name": "test", "config": {"command": "test"}},
        )
        assert response.status_code == 400

    def test_scope_enforcement(self) -> None:
        from fastapi.testclient import TestClient

        from agent33.main import app
        from agent33.security.auth import create_access_token

        # No scopes at all
        token = create_access_token("no-scope", scopes=[])
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        response = client.post(
            "/v1/component-security/mcp-servers",
            json={
                "name": "test",
                "transport": "stdio",
                "config": {"command": "test"},
            },
        )
        assert response.status_code == 403

        response = client.get("/v1/component-security/mcp-servers")
        assert response.status_code == 403

        response = client.delete("/v1/component-security/mcp-servers/test")
        assert response.status_code == 403
