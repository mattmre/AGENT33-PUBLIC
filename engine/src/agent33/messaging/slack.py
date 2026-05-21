"""Slack Web API adapter using plain httpx."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

from agent33.messaging.boundary import execute_messaging_boundary_call
from agent33.messaging.models import ChannelHealthResult, Message

logger = logging.getLogger(__name__)

_API_BASE = "https://slack.com/api"


class SlackAdapter:
    """MessagingAdapter implementation for Slack."""

    def __init__(self, bot_token: str, signing_secret: str) -> None:
        self._bot_token = bot_token
        self._signing_secret = signing_secret
        self._client: httpx.AsyncClient | None = None
        self._queue: asyncio.Queue[Message] = asyncio.Queue()

    @property
    def platform(self) -> str:
        return "slack"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=_API_BASE,
            headers={
                "Authorization": f"Bearer {self._bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            timeout=30,
        )
        logger.info("SlackAdapter started")

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("SlackAdapter stopped")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, channel_id: str, text: str) -> None:
        client = self._ensure_client()
        connector = "messaging:slack"
        operation = "send"

        async def _perform_send(_request: object) -> httpx.Response:
            return await client.post(
                "/chat.postMessage",
                json={"channel": channel_id, "text": text},
            )

        resp = await execute_messaging_boundary_call(
            connector=connector,
            operation=operation,
            payload={"channel_id": channel_id},
            metadata={"platform": self.platform},
            call=_perform_send,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    async def receive(self) -> Message:
        return await self._queue.get()

    def enqueue_event(self, payload: dict[str, Any]) -> None:
        """Parse a Slack Events API payload and enqueue it."""
        event = payload.get("event", {})
        event_type = event.get("type")
        if event_type != "message":
            return
        # Ignore bot messages to avoid loops
        if event.get("bot_id"):
            return
        self._queue.put_nowait(
            Message(
                platform="slack",
                channel_id=str(event.get("channel", "")),
                user_id=str(event.get("user", "")),
                text=event.get("text", ""),
                metadata={"raw": payload},
            )
        )

    def verify_signature(self, timestamp: str, body: bytes, signature: str) -> bool:
        """Verify Slack request signature using the signing secret."""
        # Reject requests older than 5 minutes
        if abs(time.time() - float(timestamp)) > 300:
            return False
        sig_basestring = f"v0:{timestamp}:{body.decode()}"
        computed = (
            "v0="
            + hmac.new(
                self._signing_secret.encode(),
                sig_basestring.encode(),
                hashlib.sha256,
            ).hexdigest()
        )
        return hmac.compare_digest(computed, signature)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> ChannelHealthResult:
        """Probe Slack API via auth.test and return health status."""
        if self._client is None:
            return ChannelHealthResult(
                platform="slack",
                status="unavailable",
                detail="Adapter not started",
                queue_depth=self._queue.qsize(),
            )
        client = self._client
        assert client is not None
        start = time.monotonic()
        try:
            connector = "messaging:slack"
            operation = "health_check"

            async def _perform_health_check(_request: object) -> httpx.Response:
                return await client.post("/auth.test")

            resp = await execute_messaging_boundary_call(
                connector=connector,
                operation=operation,
                payload={"endpoint": "/auth.test"},
                metadata={"platform": self.platform},
                call=_perform_health_check,
            )
            latency = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    return ChannelHealthResult(
                        platform="slack",
                        status="ok",
                        latency_ms=round(latency, 2),
                        queue_depth=self._queue.qsize(),
                    )
                return ChannelHealthResult(
                    platform="slack",
                    status="degraded",
                    latency_ms=round(latency, 2),
                    detail=f"auth.test failed: {data.get('error', 'unknown')}",
                    queue_depth=self._queue.qsize(),
                )
            return ChannelHealthResult(
                platform="slack",
                status="degraded",
                latency_ms=round(latency, 2),
                detail=f"API returned status {resp.status_code}",
                queue_depth=self._queue.qsize(),
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ChannelHealthResult(
                platform="slack",
                status="unavailable",
                latency_ms=round(latency, 2),
                detail=str(exc),
                queue_depth=self._queue.qsize(),
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("SlackAdapter is not started")
        return self._client
