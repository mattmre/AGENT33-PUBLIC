"""Discord API adapter using plain httpx."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from agent33.messaging.boundary import execute_messaging_boundary_call
from agent33.messaging.models import ChannelHealthResult, Message

logger = logging.getLogger(__name__)

_API_BASE = "https://discord.com/api/v10"


class DiscordAdapter:
    """MessagingAdapter implementation for Discord via REST + webhooks."""

    def __init__(self, bot_token: str, public_key: str) -> None:
        self._bot_token = bot_token
        self._public_key = public_key
        self._client: httpx.AsyncClient | None = None
        self._queue: asyncio.Queue[Message] = asyncio.Queue()

    @property
    def platform(self) -> str:
        return "discord"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=_API_BASE,
            headers={
                "Authorization": f"Bot {self._bot_token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        logger.info("DiscordAdapter started")

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("DiscordAdapter stopped")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, channel_id: str, text: str) -> None:
        client = self._ensure_client()
        connector = "messaging:discord"
        operation = "send"

        async def _perform_send(_request: object) -> httpx.Response:
            return await client.post(
                f"/channels/{channel_id}/messages",
                json={"content": text},
            )

        resp = await execute_messaging_boundary_call(
            connector=connector,
            operation=operation,
            payload={"channel_id": channel_id},
            metadata={"platform": self.platform},
            call=_perform_send,
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    async def receive(self) -> Message:
        return await self._queue.get()

    def enqueue_interaction(self, payload: dict[str, Any]) -> None:
        """Parse a Discord interaction payload and enqueue it."""
        interaction_type = payload.get("type")
        # Type 2 = APPLICATION_COMMAND, Type 3 = MESSAGE_COMPONENT
        if interaction_type not in (2, 3):
            return
        data = payload.get("data", {})
        user = payload.get("member", {}).get("user", {}) or payload.get("user", {})
        channel_id = payload.get("channel_id", "")
        text = data.get("name", "") if interaction_type == 2 else data.get("custom_id", "")
        # For slash commands, include options as text
        options = data.get("options", [])
        if options:
            parts = [text]
            for opt in options:
                parts.append(f"{opt.get('name', '')}={opt.get('value', '')}")
            text = " ".join(parts)

        self._queue.put_nowait(
            Message(
                platform="discord",
                channel_id=str(channel_id),
                user_id=str(user.get("id", "")),
                text=text,
                metadata={"raw": payload},
            )
        )

    def verify_signature(self, signature: str, timestamp: str, body: bytes) -> bool:
        """Verify Discord Ed25519 request signature."""
        try:
            from nacl.signing import VerifyKey
        except ImportError:
            logger.warning("PyNaCl not installed; skipping Discord signature verification")
            return True

        vk = VerifyKey(bytes.fromhex(self._public_key))
        try:
            vk.verify(timestamp.encode() + body, bytes.fromhex(signature))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> ChannelHealthResult:
        """Probe Discord API via GET /users/@me and return health status."""
        if self._client is None:
            return ChannelHealthResult(
                platform="discord",
                status="unavailable",
                detail="Adapter not started",
                queue_depth=self._queue.qsize(),
            )
        client = self._client
        assert client is not None
        start = time.monotonic()
        try:
            connector = "messaging:discord"
            operation = "health_check"

            async def _perform_health_check(_request: object) -> httpx.Response:
                return await client.get("/users/@me")

            resp = await execute_messaging_boundary_call(
                connector=connector,
                operation=operation,
                payload={"endpoint": "/users/@me"},
                metadata={"platform": self.platform},
                call=_perform_health_check,
            )
            latency = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                return ChannelHealthResult(
                    platform="discord",
                    status="ok",
                    latency_ms=round(latency, 2),
                    queue_depth=self._queue.qsize(),
                )
            return ChannelHealthResult(
                platform="discord",
                status="degraded",
                latency_ms=round(latency, 2),
                detail=f"API returned status {resp.status_code}",
                queue_depth=self._queue.qsize(),
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ChannelHealthResult(
                platform="discord",
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
            raise RuntimeError("DiscordAdapter is not started")
        return self._client
