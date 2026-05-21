"""HTTP request metrics middleware for availability and latency SLO tracking."""

from __future__ import annotations

import re
import time
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.types import ASGIApp

    from agent33.observability.metrics import MetricsCollector

# Pre-compiled patterns for path normalization
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
)
_NUMERIC_SEGMENT_RE = re.compile(r"/\d+(/|$)")


class HTTPMetricsMiddleware(BaseHTTPMiddleware):
    """Records HTTP request count and latency for SLO tracking.

    Emits two metric families per request:

    * ``http_requests_total`` -- counter with method/path/status_code labels
    * ``http_request_duration_seconds`` -- observation with method/path labels

    The *collector* parameter is optional.  When ``None``, the middleware
    resolves the collector lazily from ``request.app.state.metrics_collector``
    on each request.  This allows the middleware to be registered at module
    scope before the lifespan creates the collector.
    """

    def __init__(
        self,
        app: ASGIApp,
        collector: MetricsCollector | None = None,
    ) -> None:
        super().__init__(app)
        self._collector = collector

    def _resolve_collector(self, request: Request) -> MetricsCollector | None:
        if self._collector is not None:
            return self._collector
        result: MetricsCollector | None = getattr(request.app.state, "metrics_collector", None)
        return result

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        collector = self._resolve_collector(request)
        if collector is None:
            # Collector not yet available (pre-lifespan); pass through.
            result: Response = await call_next(request)
            return result

        start = time.perf_counter()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration = time.perf_counter() - start
            status = str(response.status_code) if response else "500"
            path = normalize_path(request.url.path)
            method = request.method
            labels = {
                "method": method,
                "path": path,
                "status_code": status,
            }
            collector.increment("http_requests_total", labels)
            collector.observe(
                "http_request_duration_seconds",
                duration,
                {"method": method, "path": path},
            )


def normalize_path(path: str) -> str:
    """Collapse UUID and numeric path segments to reduce metric cardinality."""
    # Replace UUIDs
    path = _UUID_RE.sub("{id}", path)
    # Replace pure numeric segments
    path = _NUMERIC_SEGMENT_RE.sub(r"/{id}\1", path)
    return path
