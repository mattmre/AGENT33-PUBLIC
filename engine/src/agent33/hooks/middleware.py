"""HookMiddleware: Starlette BaseHTTPMiddleware for request lifecycle hooks."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from agent33.hooks.models import HookEventType, RequestHookContext

if TYPE_CHECKING:
    from starlette.requests import Request

    from agent33.hooks.registry import HookRegistry

logger = logging.getLogger(__name__)


class HookMiddleware(BaseHTTPMiddleware):
    """Starlette middleware that fires request.pre and request.post hooks.

    Must be positioned in the middleware stack so that it runs AFTER
    AuthMiddleware (so ``request.state.user`` is populated for tenant_id
    resolution).

    The hook_registry is read from ``request.app.state.hook_registry``.
    If not present, the middleware is a no-op pass-through.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        hook_registry: HookRegistry | None = getattr(request.app.state, "hook_registry", None)
        if hook_registry is None:
            return await call_next(request)

        # Resolve tenant from auth middleware
        user = getattr(request.state, "user", None)
        tenant_id = getattr(user, "tenant_id", "") if user else ""

        start = time.monotonic()

        # --- Request PRE hooks ---
        pre_hooks = hook_registry.get_hooks(HookEventType.REQUEST_PRE, tenant_id)
        if pre_hooks:
            pre_runner = hook_registry.get_chain_runner(HookEventType.REQUEST_PRE, tenant_id)
            # Build pre-hook context with available request data
            headers_dict: dict[str, str] = {}
            for key, value in request.headers.items():
                headers_dict[key] = value

            pre_ctx = RequestHookContext(
                event_type=HookEventType.REQUEST_PRE,
                tenant_id=tenant_id,
                metadata={},
                method=request.method,
                path=str(request.url.path),
                headers=headers_dict,
            )
            pre_result = await pre_runner.run(pre_ctx)
            if pre_result.abort:
                logger.info(
                    "request_hook_abort path=%s reason=%s",
                    request.url.path,
                    pre_result.abort_reason,
                )
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Request blocked by hook: {pre_result.abort_reason}"},
                )

        # --- Execute actual request ---
        response: Response = await call_next(request)

        # --- Request POST hooks ---
        post_hooks = hook_registry.get_hooks(HookEventType.REQUEST_POST, tenant_id)
        if post_hooks:
            post_runner = hook_registry.get_chain_runner(HookEventType.REQUEST_POST, tenant_id)
            duration_ms = (time.monotonic() - start) * 1000
            response_headers: dict[str, str] = {}
            for key, value in response.headers.items():
                response_headers[key] = value

            post_ctx = RequestHookContext(
                event_type=HookEventType.REQUEST_POST,
                tenant_id=tenant_id,
                metadata={},
                method=request.method,
                path=str(request.url.path),
                status_code=response.status_code,
                response_headers=response_headers,
                duration_ms=round(duration_ms, 2),
            )
            await post_runner.run(post_ctx)
            # Post hooks cannot modify the response (already sent)

        return response
