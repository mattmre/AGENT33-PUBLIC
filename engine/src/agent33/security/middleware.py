"""FastAPI authentication middleware."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from jwt import InvalidTokenError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from agent33.security.auth import validate_api_key, verify_token

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger(__name__)

_PUBLIC_PATHS: set[str] = {
    "/health",
    "/healthz",
    "/readyz",
    "/health/channels",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/v1/auth/token",
    "/v1/dashboard/",
    "/v1/outcomes/health",
    "/v1/ingestion/heartbeat",
}


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce authentication on every request except public paths.

    Supports two schemes:

    * ``Authorization: Bearer <jwt>``
    * ``X-API-Key: <key>``

    On success the decoded :class:`~agent33.security.auth.TokenPayload` is
    attached to ``request.state.user``.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Let CORS middleware handle preflight.
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow public endpoints through without auth
        if (
            path in _PUBLIC_PATHS
            or path.startswith("/v1/dashboard/")
            or path == "/docs"
            or path.startswith("/docs/")
            or path == "/redoc"
            or path.startswith("/redoc/")
        ):
            return await call_next(request)

        # Try Bearer token
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                payload = verify_token(token)
            except InvalidTokenError:
                logger.debug("http_token_invalid path=%s", path)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid or expired token"},
                )
            request.state.user = payload
            return await call_next(request)

        # Try API key
        api_key = request.headers.get("X-API-Key")
        if api_key:
            api_payload = validate_api_key(api_key)
            if api_payload is not None:
                request.state.user = api_payload
                return await call_next(request)
            return JSONResponse(status_code=401, content={"detail": "Invalid API key"})

        return JSONResponse(
            status_code=401,
            content={"detail": "Missing authentication credentials"},
        )
