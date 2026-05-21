"""Connector middleware-chain executor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agent33.connectors.middleware import ConnectorHandler, ConnectorMiddleware
    from agent33.connectors.models import ConnectorRequest

logger = structlog.get_logger()


class ConnectorExecutor:
    """Executes connector boundary operations through middleware."""

    def __init__(self, middlewares: Sequence[ConnectorMiddleware] | None = None) -> None:
        self._middlewares: list[ConnectorMiddleware] = list(middlewares or [])

    async def execute(self, request: ConnectorRequest, handler: ConnectorHandler) -> Any:
        """Run *handler* through configured middleware in declaration order."""
        next_handler = handler
        for middleware in reversed(self._middlewares):
            current = middleware
            downstream = next_handler

            async def wrapped(
                req: ConnectorRequest,
                m: ConnectorMiddleware = current,
                n: ConnectorHandler = downstream,
            ) -> Any:
                return await m(req, n)

            next_handler = wrapped
        return await next_handler(request)
