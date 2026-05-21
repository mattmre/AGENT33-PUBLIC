"""Tests for the ReaderTool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from agent33.tools.base import ToolContext
from agent33.tools.builtin.reader import ReaderTool


@pytest.fixture
def tool() -> ReaderTool:
    return ReaderTool()


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(domain_allowlist=["example.com"])


async def test_name(tool: ReaderTool) -> None:
    assert tool.name == "reader"


async def test_missing_url(tool: ReaderTool, context: ToolContext) -> None:
    result = await tool.execute({}, context)
    assert not result.success


async def test_domain_allowlist_blocks(tool: ReaderTool) -> None:
    ctx = ToolContext(domain_allowlist=["allowed.com"])
    result = await tool.execute({"url": "https://blocked.com/page"}, ctx)
    assert not result.success
    assert "not in allowlist" in result.error.lower() or "allow" in result.error.lower()


@patch("agent33.tools.builtin.reader.settings")
async def test_jina_api_mode(
    mock_settings: AsyncMock, tool: ReaderTool, context: ToolContext
) -> None:
    mock_settings.jina_api_key = SecretStr("test-key")
    mock_settings.jina_reader_url = "https://r.jina.ai"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"content": "# Hello World"}
    mock_resp.raise_for_status = MagicMock()

    with patch("agent33.tools.builtin.reader.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = await tool.execute({"url": "https://example.com"}, context)
        assert result.success
        assert "Hello World" in result.output


@patch("agent33.tools.builtin.reader.settings")
async def test_local_fallback(
    mock_settings: AsyncMock, tool: ReaderTool, context: ToolContext
) -> None:
    mock_settings.jina_api_key = SecretStr("")

    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_resp.text = "<html><body><p>Test content here</p></body></html>"
    mock_resp.raise_for_status = MagicMock()

    with patch("agent33.tools.builtin.reader.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = await tool.execute({"url": "https://example.com"}, context)
        assert result.success
        assert "Test content" in result.output or len(result.output) > 0


@patch("agent33.tools.builtin.reader.settings")
async def test_jina_invalid_json_response(
    mock_settings: AsyncMock, tool: ReaderTool, context: ToolContext
) -> None:
    mock_settings.jina_api_key = SecretStr("test-key")
    mock_settings.jina_reader_url = "https://r.jina.ai"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.side_effect = ValueError("not json")

    with patch("agent33.tools.builtin.reader.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        result = await tool.execute({"url": "https://example.com"}, context)
        assert result.success is False
        assert result.error == "Jina returned invalid JSON response"
