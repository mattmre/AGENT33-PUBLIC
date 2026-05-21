"""HTTP fetch tool with domain allowlist and size limits."""

from __future__ import annotations

from typing import Any

from agent33.tools.base import ToolContext, ToolResult
from agent33.web_research import create_default_web_research_service

_DEFAULT_TIMEOUT = 30


class WebFetchTool:
    """Perform HTTP GET/POST requests with governance controls."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Fetch a URL via HTTP GET or POST, returning the response body."

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Fetch a URL.

        Parameters
        ----------
        params:
            url     : str            - Target URL.
            method  : str            - 'GET' or 'POST' (default GET).
            headers : dict[str,str]  - Optional extra headers.
            body    : str            - Optional request body for POST.
            timeout : int            - Seconds (default 30).
        """
        url: str = params.get("url", "").strip()
        if not url:
            return ToolResult.fail("No URL provided")

        method: str = params.get("method", "GET").upper()
        if method not in ("GET", "POST"):
            return ToolResult.fail(f"Unsupported method: {method}")

        headers: dict[str, str] = params.get("headers", {})
        body: str | None = params.get("body")
        timeout: int = params.get("timeout", _DEFAULT_TIMEOUT)

        try:
            service = create_default_web_research_service()
            artifact = await service.fetch(
                url,
                allowed_domains=context.domain_allowlist,
                headers=headers,
                body=body,
                method=method,
                timeout=timeout,
            )
        except ValueError as exc:
            return ToolResult.fail(str(exc))

        return ToolResult.ok(artifact.content)
