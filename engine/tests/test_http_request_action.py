"""Tests for the http_request workflow action.

Covers SSRF protection (_is_private_url), execute() happy/error paths,
header handling, dry-run mode, method propagation, and edge cases.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent33.workflows.actions.http_request import (
    _is_private_url,
    execute,
)

_PATCH_BOUNDARY = "agent33.workflows.actions.http_request.build_connector_boundary_executor"
_PATCH_CLIENT = "agent33.workflows.actions.http_request.httpx.AsyncClient"


# ---------------------------------------------------------------------------
# _is_private_url: SSRF protection
# ---------------------------------------------------------------------------


class TestIsPrivateUrl:
    """Verify that private/reserved IP addresses and localhost are blocked."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/secret",
            "http://127.0.0.255/path",
            "http://10.0.0.1/internal",
            "http://10.255.255.255/path",
            "http://172.16.0.1/path",
            "http://172.31.255.255/path",
            "http://192.168.0.1/path",
            "http://192.168.255.255/path",
            "http://169.254.1.1/metadata",
            "http://localhost/admin",
            "http://localhost./admin",
            "http://LOCALHOST/admin",
        ],
        ids=[
            "loopback-127.0.0.1",
            "loopback-127.0.0.255",
            "class-A-10.0.0.1",
            "class-A-10.255.255.255",
            "class-B-172.16.0.1",
            "class-B-172.31.255.255",
            "class-C-192.168.0.1",
            "class-C-192.168.255.255",
            "link-local-169.254",
            "localhost",
            "localhost-trailing-dot",
            "localhost-uppercase",
        ],
    )
    def test_blocks_private_addresses(self, url: str) -> None:
        assert _is_private_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "http://[::1]/secret",
            "http://[fc00::1]/path",
            "http://[fe80::1]/path",
        ],
        ids=[
            "ipv6-loopback",
            "ipv6-unique-local",
            "ipv6-link-local",
        ],
    )
    def test_blocks_private_ipv6(self, url: str) -> None:
        assert _is_private_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "http://8.8.8.8/dns",
            "http://93.184.216.34/page",
            "https://api.example.com/v1",
            "http://172.32.0.1/outside-range",
        ],
        ids=[
            "google-dns",
            "public-ip",
            "dns-hostname",
            "just-outside-172-range",
        ],
    )
    def test_allows_public_addresses(self, url: str) -> None:
        assert _is_private_url(url) is False

    def test_missing_hostname_returns_false(self) -> None:
        """A URL with no hostname (e.g. relative path) is not flagged."""
        assert _is_private_url("/relative/path") is False


# ---------------------------------------------------------------------------
# execute(): validation and dry-run
# ---------------------------------------------------------------------------


class TestExecuteValidation:
    """Validate input checks before any HTTP call is made."""

    async def test_empty_url_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="requires a 'url' field"):
            await execute(url="")

    async def test_none_url_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="requires a 'url' field"):
            await execute(url=None)

    async def test_private_ip_raises_ssrf_error(self) -> None:
        with pytest.raises(ValueError, match="SSRF protection"):
            await execute(url="http://10.0.0.1/internal")

    @patch(_PATCH_BOUNDARY, return_value=None)
    async def test_dry_run_returns_without_request(self, _mock_boundary: MagicMock) -> None:
        result = await execute(url="https://example.com", method="POST", dry_run=True)
        assert result == {
            "dry_run": True,
            "url": "https://example.com",
            "method": "POST",
        }


# ---------------------------------------------------------------------------
# execute(): mocked HTTP responses
# ---------------------------------------------------------------------------


def _fake_response(
    status_code: int = 200,
    text: str = '{"ok": true}',
    headers: dict[str, str] | None = None,
    json_data: object | None = None,
) -> MagicMock:
    """Build a mock httpx.Response with the given attributes."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.headers = httpx.Headers(headers or {"content-type": "application/json"})
    if json_data is not None:
        resp.json.return_value = json_data
    else:
        try:
            import json

            resp.json.return_value = json.loads(text)
        except (ValueError, TypeError):
            resp.json.side_effect = ValueError("not JSON")
    return resp


def _mock_async_client(
    response: MagicMock | None = None,
    side_effect: Exception | None = None,
) -> AsyncMock:
    """Build a mock httpx.AsyncClient context manager."""
    client = AsyncMock()
    if side_effect is not None:
        client.request.side_effect = side_effect
    else:
        client.request.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


class TestExecuteRequests:
    """Test execute() with mocked httpx calls (no real network)."""

    @patch(_PATCH_BOUNDARY, return_value=None)
    async def test_get_success_returns_structured_response(
        self, _mock_boundary: MagicMock
    ) -> None:
        fake_resp = _fake_response(
            status_code=200,
            text='{"result": "ok"}',
            json_data={"result": "ok"},
        )
        mock_client = _mock_async_client(response=fake_resp)

        with patch(_PATCH_CLIENT, return_value=mock_client):
            result = await execute(url="https://api.example.com/data", method="GET")

        assert result["status_code"] == 200
        assert result["json"] == {"result": "ok"}
        assert result["body"] == '{"result": "ok"}'
        assert "content-type" in result["headers"]
        mock_client.request.assert_called_once_with(
            "GET", "https://api.example.com/data", headers={}
        )

    @patch(_PATCH_BOUNDARY, return_value=None)
    async def test_post_with_json_body(self, _mock_boundary: MagicMock) -> None:
        fake_resp = _fake_response(status_code=201, text='{"id": 42}', json_data={"id": 42})
        mock_client = _mock_async_client(response=fake_resp)

        with patch(_PATCH_CLIENT, return_value=mock_client):
            result = await execute(
                url="https://api.example.com/items",
                method="POST",
                body={"name": "widget"},
                headers={"Authorization": "Bearer tok"},
            )

        assert result["status_code"] == 201
        assert result["json"] == {"id": 42}
        # Verify json kwarg was used (dict body), not content
        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs.get("json") == {"name": "widget"}
        assert "content" not in call_kwargs.kwargs
        assert call_kwargs.kwargs["headers"] == {
            "Authorization": "Bearer tok",
        }

    @patch(_PATCH_BOUNDARY, return_value=None)
    async def test_post_with_string_body_uses_content(self, _mock_boundary: MagicMock) -> None:
        fake_resp = _fake_response(status_code=200, text="ok")
        mock_client = _mock_async_client(response=fake_resp)

        with patch(_PATCH_CLIENT, return_value=mock_client):
            await execute(
                url="https://api.example.com/upload",
                method="POST",
                body="raw text payload",
            )

        call_kwargs = mock_client.request.call_args
        assert call_kwargs.kwargs.get("content") == "raw text payload"
        assert "json" not in call_kwargs.kwargs

    @patch(_PATCH_BOUNDARY, return_value=None)
    async def test_timeout_raises_runtime_error(self, _mock_boundary: MagicMock) -> None:
        mock_client = _mock_async_client(
            side_effect=httpx.TimeoutException("timed out"),
        )

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            pytest.raises(RuntimeError, match="HTTP request timed out"),
        ):
            await execute(
                url="https://slow.example.com/api",
                timeout_seconds=5,
            )

    @patch(_PATCH_BOUNDARY, return_value=None)
    async def test_connect_error_raises_runtime_error(self, _mock_boundary: MagicMock) -> None:
        mock_client = _mock_async_client(
            side_effect=httpx.ConnectError("connection refused"),
        )

        with (
            patch(_PATCH_CLIENT, return_value=mock_client),
            pytest.raises(RuntimeError, match="Connection failed"),
        ):
            await execute(url="https://unreachable.example.com/api")

    @patch(_PATCH_BOUNDARY, return_value=None)
    async def test_non_json_response_sets_json_to_none(self, _mock_boundary: MagicMock) -> None:
        fake_resp = _fake_response(
            status_code=200,
            text="<html>hello</html>",
        )
        # json() should raise for non-JSON content
        fake_resp.json.side_effect = ValueError("not JSON")
        mock_client = _mock_async_client(response=fake_resp)

        with patch(_PATCH_CLIENT, return_value=mock_client):
            result = await execute(url="https://example.com/page")

        assert result["status_code"] == 200
        assert result["body"] == "<html>hello</html>"
        assert result["json"] is None

    @patch(_PATCH_BOUNDARY, return_value=None)
    async def test_custom_timeout_propagated_to_client(self, _mock_boundary: MagicMock) -> None:
        fake_resp = _fake_response()
        mock_client = _mock_async_client(response=fake_resp)

        with patch(
            _PATCH_CLIENT,
            return_value=mock_client,
        ) as mock_cls:
            await execute(url="https://example.com/api", timeout_seconds=60)

        # AsyncClient was constructed with the custom timeout
        mock_cls.assert_called_once_with(timeout=60, follow_redirects=False)
