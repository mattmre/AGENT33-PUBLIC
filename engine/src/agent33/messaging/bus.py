"""NATS-based message bus for internal event routing."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

try:
    import nats

    _NATS_AVAILABLE = True
except ImportError:  # pragma: no cover
    nats = None  # type: ignore[assignment]
    _NATS_AVAILABLE = False

from agent33.config import settings

if TYPE_CHECKING:
    from nats.aio.client import Client as NATSClient
    from nats.aio.msg import Msg

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class NATSMessageBus:
    """Thin wrapper around a NATS connection for pub/sub and request/reply."""

    def __init__(self, url: str | None = None) -> None:
        if not _NATS_AVAILABLE:
            raise RuntimeError(
                "NATS dependencies are not installed. Install with: pip install agent33[standard]"
            )
        self._url = url or settings.nats_url
        self._nc: NATSClient | None = None
        self._subscriptions: list[Any] = []

    @property
    def is_connected(self) -> bool:
        return self._nc is not None and self._nc.is_connected

    async def connect(self) -> None:
        """Open the NATS connection."""
        if self.is_connected:
            return
        self._nc = await nats.connect(self._url)
        logger.info("NATS connected to %s", self._url)

    async def close(self) -> None:
        """Drain subscriptions and close the connection."""
        if self._nc is not None:
            await self._nc.drain()
            self._nc = None
            self._subscriptions.clear()
            logger.info("NATS connection closed")

    async def publish(self, subject: str, data: dict[str, Any]) -> None:
        """Publish a JSON-encoded message to *subject*."""
        if self._nc is None:
            raise RuntimeError("Not connected to NATS")
        payload = json.dumps(data).encode()
        await self._nc.publish(subject, payload)

    async def subscribe(self, subject: str, handler: Handler) -> None:
        """Subscribe to *subject* and invoke *handler* for each message.

        The handler receives the decoded JSON payload as a ``dict``.
        """
        if self._nc is None:
            raise RuntimeError("Not connected to NATS")

        async def _cb(msg: Msg) -> None:
            try:
                data = json.loads(msg.data.decode())
                await handler(data)
            except Exception:
                logger.exception("Error handling NATS message on %s", subject)

        sub = await self._nc.subscribe(subject, cb=_cb)
        self._subscriptions.append(sub)

    async def request(
        self,
        subject: str,
        data: dict[str, Any],
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Send a request to *subject* and return the JSON-decoded reply."""
        if self._nc is None:
            raise RuntimeError("Not connected to NATS")
        payload = json.dumps(data).encode()
        reply: Msg = await self._nc.request(subject, payload, timeout=timeout)
        result: dict[str, Any] = json.loads(reply.data.decode())
        return result
