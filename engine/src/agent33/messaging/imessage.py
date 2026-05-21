"""iMessage adapter using BlueBubbles or AppleScript wrapper."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from agent33.messaging.boundary import execute_messaging_boundary_call
from agent33.messaging.models import ChannelHealthResult, Message

logger = logging.getLogger(__name__)


class IMessageAdapter:
    """MessagingAdapter implementation for iMessage via Mac Bridge."""

    def __init__(self, bridge_url: str) -> None:
        self._bridge_url = bridge_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None
        self._queue: asyncio.Queue[Message] = asyncio.Queue()
        self._running = False

    @property
    def platform(self) -> str:
        return "imessage"

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=30)
        self._running = True
        logger.info("IMessageAdapter started")

    async def stop(self) -> None:
        self._running = False
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("IMessageAdapter stopped")

    async def send(self, channel_id: str, text: str) -> None:
        client = self._ensure_client()
        connector = "messaging:imessage"
        operation = "send"

        async def _perform_send(_request: object) -> httpx.Response:
            return await client.post(
                f"{self._bridge_url}/api/v1/message/text",
                json={"chatGuid": channel_id, "text": text},
            )

        resp = await execute_messaging_boundary_call(
            connector=connector,
            operation=operation,
            payload={"channel_id": channel_id},
            metadata={"platform": self.platform},
            call=_perform_send,
        )
        resp.raise_for_status()

    async def receive(self) -> Message:
        return await self._queue.get()

    def enqueue_message(self, payload: dict[str, Any]) -> None:
        """Parse incoming BlueBubbles webhook data."""
        handle = payload.get("data", {}).get("handle", {}).get("address")
        text = payload.get("data", {}).get("text")
        guid = payload.get("data", {}).get("chats", [{}])[0].get("guid")

        if not text or not guid:
            return

        self._queue.put_nowait(
            Message(
                platform="imessage",
                channel_id=guid,
                user_id=handle or "unknown",
                text=text,
                metadata={"raw": payload},
            )
        )

    async def health_check(self) -> ChannelHealthResult:
        if self._client is None:
            return ChannelHealthResult(
                platform="imessage",
                status="unavailable",
                detail="Not started",
                queue_depth=self._queue.qsize(),
            )
        client = self._client
        assert client is not None
        start = time.monotonic()
        try:
            connector = "messaging:imessage"
            operation = "health_check"

            async def _perform_health_check(_request: object) -> httpx.Response:
                return await client.get(f"{self._bridge_url}/api/v1/ping")

            resp = await execute_messaging_boundary_call(
                connector=connector,
                operation=operation,
                payload={"endpoint": f"{self._bridge_url}/api/v1/ping"},
                metadata={"platform": self.platform},
                call=_perform_health_check,
            )
            latency = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                return ChannelHealthResult(
                    platform="imessage",
                    status="ok" if self._running else "degraded",
                    latency_ms=round(latency, 2),
                    detail="",
                    queue_depth=self._queue.qsize(),
                )
            return ChannelHealthResult(
                platform="imessage",
                status="degraded",
                latency_ms=round(latency, 2),
                detail=f"Status {resp.status_code}",
                queue_depth=self._queue.qsize(),
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ChannelHealthResult(
                platform="imessage",
                status="unavailable",
                latency_ms=round(latency, 2),
                detail=str(exc),
                queue_depth=self._queue.qsize(),
            )

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("IMessageAdapter is not started")
        return self._client
