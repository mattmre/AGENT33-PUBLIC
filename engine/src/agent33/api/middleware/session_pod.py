"""Session pod identity middleware for debugging affinity.

Adds an ``X-Agent33-Session-Pod`` response header containing the pod hostname
so operators can verify that session-affinity routing is working correctly.
The header value comes from the ``HOSTNAME`` environment variable (set by K8s
on every pod) with a fallback to ``COMPUTERNAME`` on Windows and ``"unknown"``
otherwise.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.requests import Request
    from starlette.responses import Response

_HEADER_NAME = "X-Agent33-Session-Pod"


class SessionPodMiddleware(BaseHTTPMiddleware):
    """Injects ``X-Agent33-Session-Pod`` header into every response."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        response: Response = await call_next(request)
        pod_name = os.environ.get("HOSTNAME", os.environ.get("COMPUTERNAME", "unknown"))
        response.headers[_HEADER_NAME] = pod_name
        return response
