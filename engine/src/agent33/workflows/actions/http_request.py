"""Action that performs an HTTP request as a workflow step."""

from __future__ import annotations

import ipaddress
from typing import Any, cast
from urllib.parse import urlparse

import httpx
import structlog

from agent33.connectors.boundary import (
    build_connector_boundary_executor,
    map_connector_exception,
)
from agent33.connectors.models import ConnectorRequest

logger = structlog.get_logger()

# Private/reserved IP ranges that should be blocked to prevent SSRF.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_url(url: str) -> bool:
    """Return True if the URL targets a private/reserved IP range."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if hostname is None:
        return False
    try:
        addr = ipaddress.ip_address(hostname)
        return any(addr in net for net in _BLOCKED_NETWORKS)
    except ValueError:
        # Not an IP literal — allow DNS names (could still resolve
        # to private IPs but DNS resolution happens at the HTTP
        # client level, not here).
        return hostname.lower() in ("localhost", "localhost.")


async def execute(
    url: str | None,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: Any | None = None,
    timeout_seconds: int = 30,
    inputs: dict[str, Any] | None = None,
    dry_run: bool = False,
    policy_pack: str | None = None,
) -> dict[str, Any]:
    """Make an HTTP request and return the response.

    Args:
        url: Target URL (required).
        method: HTTP method (GET, POST, PUT, etc.).
        headers: Optional request headers.
        body: Optional request body (dict/list sends as JSON,
            anything else as text).
        timeout_seconds: Per-request HTTP client timeout in seconds.
            When using retries at the workflow step level, ensure
            this value leaves room for multiple attempts within the
            overall step timeout.
        inputs: Additional context (unused, kept for action signature
            consistency).
        dry_run: If True, log but skip actual request.

    Returns:
        A dict with ``status_code``, ``headers``, ``body`` (text),
        and ``json`` (parsed JSON or None).

    Raises:
        ValueError: If *url* is not provided or targets a private IP.
    """
    if not url:
        raise ValueError("http-request action requires a 'url' field")

    if _is_private_url(url):
        raise ValueError(
            f"SSRF protection: requests to private/reserved addresses are blocked ({url})"
        )

    logger.info("http_request", url=url, method=method, dry_run=dry_run)

    if dry_run:
        return {"dry_run": True, "url": url, "method": method}

    connector = "workflow:http_request"
    operation = method.upper()

    async def _do_request(_request: ConnectorRequest) -> dict[str, Any]:
        return await _perform_request(
            method=method,
            url=url,
            headers=headers,
            body=body,
            timeout_seconds=timeout_seconds,
        )

    boundary_executor = build_connector_boundary_executor(
        default_timeout_seconds=float(timeout_seconds),
        retry_attempts=1,
        policy_pack=policy_pack,
    )
    if boundary_executor is not None:
        request = ConnectorRequest(
            connector=connector,
            operation=operation,
            payload={"url": url, "headers": headers or {}, "body": body},
            metadata={"timeout_seconds": float(timeout_seconds)},
        )
        try:
            return cast("dict[str, Any]", await boundary_executor.execute(request, _do_request))
        except Exception as exc:
            raise map_connector_exception(exc, connector, operation) from exc

    return await _perform_request(
        method=method,
        url=url,
        headers=headers,
        body=body,
        timeout_seconds=timeout_seconds,
    )


async def _perform_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None,
    body: Any | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
        ) as client:
            kwargs: dict[str, Any] = {"headers": headers or {}}
            if body is not None:
                if isinstance(body, (dict, list)):
                    kwargs["json"] = body
                else:
                    kwargs["content"] = str(body)
            response = await client.request(method, url, **kwargs)
    except httpx.TimeoutException as exc:
        raise RuntimeError(f"HTTP request timed out: {url}") from exc
    except httpx.ConnectError as exc:
        raise RuntimeError(f"Connection failed: {url} — {exc}") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError(f"HTTP error: {url} — {exc}") from exc

    response_body = response.text
    try:
        response_json = response.json()
    except Exception:
        response_json = None

    logger.info(
        "http_request_complete",
        url=url,
        status_code=response.status_code,
    )

    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body": response_body,
        "json": response_json,
    }
