"""Reader tool that converts URLs to clean markdown."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

import httpx

from agent33.config import settings
from agent33.connectors.boundary import (
    build_connector_boundary_executor,
    map_connector_exception,
)
from agent33.connectors.models import ConnectorRequest
from agent33.tools.base import ToolContext, ToolResult

try:
    import trafilatura
except ImportError:  # pragma: no cover
    trafilatura = None

_TIMEOUT = 30
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # 5 MB


def _strip_tags(html: str) -> str:
    """Naive HTML-to-text fallback using regex."""
    text = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    text = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class ReaderTool:
    """Convert a URL to clean markdown content.

    Uses the Jina Reader API when ``JINA_API_KEY`` is configured,
    otherwise falls back to local extraction via *trafilatura* (preferred)
    or simple HTML tag stripping.
    """

    @property
    def name(self) -> str:
        return "reader"

    @property
    def description(self) -> str:
        return "Fetch a URL and return its content as clean markdown."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Fetch *url* and return markdown.

        Parameters
        ----------
        params:
            url : str - The URL to read.
        """
        url: str = params.get("url", "").strip()
        if not url:
            return ToolResult.fail("No URL provided")

        parsed = urlparse(url)
        domain = parsed.hostname or ""

        if not context.domain_allowlist:
            return ToolResult.fail(
                "Domain allowlist not configured — all requests denied by default"
            )
        if not any(
            domain == allowed or domain.endswith(f".{allowed}")
            for allowed in context.domain_allowlist
        ):
            return ToolResult.fail(
                f"Domain '{domain}' is not in the allowlist: {context.domain_allowlist}"
            )

        boundary_executor = build_connector_boundary_executor(
            default_timeout_seconds=float(_TIMEOUT),
            retry_attempts=1,
        )

        if settings.jina_api_key.get_secret_value():
            return await self._jina_fetch(url, boundary_executor)

        return await self._local_fetch(url, boundary_executor)

    # ------------------------------------------------------------------
    # Jina Reader path
    # ------------------------------------------------------------------

    async def _jina_fetch(
        self,
        url: str,
        boundary_executor: Any,
    ) -> ToolResult:
        jina_url = f"{settings.jina_reader_url.rstrip('/')}/{url}"
        headers = {
            "Authorization": f"Bearer {settings.jina_api_key.get_secret_value()}",
            "Accept": "application/json",
        }

        async def _perform_jina_fetch(_request: ConnectorRequest) -> httpx.Response:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
                return await client.get(jina_url, headers=headers)

        if boundary_executor is None:
            try:
                resp = await _perform_jina_fetch(
                    ConnectorRequest(connector="tool:reader", operation="GET")
                )
                resp.raise_for_status()
            except httpx.TimeoutException:
                return ToolResult.fail(f"Jina request timed out after {_TIMEOUT}s")
            except httpx.HTTPStatusError as exc:
                return ToolResult.fail(
                    f"Jina HTTP {exc.response.status_code}: {exc.response.text[:500]}"
                )
            except httpx.RequestError as exc:
                return ToolResult.fail(f"Jina request error: {exc}")
        else:
            try:
                req = ConnectorRequest(
                    connector="tool:reader",
                    operation="GET",
                    payload={"url": jina_url, "headers": headers},
                    metadata={"timeout_seconds": float(_TIMEOUT)},
                )
                resp = await boundary_executor.execute(req, _perform_jina_fetch)
                resp.raise_for_status()
            except Exception as exc:
                mapped = map_connector_exception(exc, "tool:reader", "GET")
                return ToolResult.fail(str(mapped))

        if 300 <= resp.status_code < 400:
            return ToolResult.fail("Jina redirect responses are blocked by policy")
        try:
            data = resp.json()
        except ValueError:
            return ToolResult.fail("Jina returned invalid JSON response")
        content: str = data.get("content", "") or data.get("text", "")
        if not content:
            return ToolResult.fail("Jina returned empty content")
        return ToolResult.ok(content)

    # ------------------------------------------------------------------
    # Local fallback path
    # ------------------------------------------------------------------

    async def _local_fetch(
        self,
        url: str,
        boundary_executor: Any,
    ) -> ToolResult:
        async def _perform_local_fetch(_request: ConnectorRequest) -> httpx.Response:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
                return await client.get(url)

        if boundary_executor is None:
            try:
                resp = await _perform_local_fetch(
                    ConnectorRequest(connector="tool:reader", operation="GET")
                )
                resp.raise_for_status()
            except httpx.TimeoutException:
                return ToolResult.fail(f"Request timed out after {_TIMEOUT}s")
            except httpx.HTTPStatusError as exc:
                return ToolResult.fail(
                    f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"
                )
            except httpx.RequestError as exc:
                return ToolResult.fail(f"Request error: {exc}")
        else:
            try:
                req = ConnectorRequest(
                    connector="tool:reader",
                    operation="GET",
                    payload={"url": url},
                    metadata={"timeout_seconds": float(_TIMEOUT)},
                )
                resp = await boundary_executor.execute(req, _perform_local_fetch)
                resp.raise_for_status()
            except Exception as exc:
                mapped = map_connector_exception(exc, "tool:reader", "GET")
                return ToolResult.fail(str(mapped))

        if len(resp.content) > _MAX_RESPONSE_BYTES:
            return ToolResult.fail(
                f"Response too large ({len(resp.content)} bytes, limit {_MAX_RESPONSE_BYTES})"
            )
        if 300 <= resp.status_code < 400:
            return ToolResult.fail("Redirect responses are blocked by policy")

        html = resp.text

        # Prefer trafilatura when available
        if trafilatura is not None:
            extracted = trafilatura.extract(
                html,
                output_format="txt",
                include_links=True,
                include_tables=True,
            )
            if extracted:
                return ToolResult.ok(extracted)

        # Fallback: regex tag stripping
        return ToolResult.ok(_strip_tags(html))
