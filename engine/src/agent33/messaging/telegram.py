"""Telegram Bot API adapter using plain httpx."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

import httpx

from agent33.messaging.boundary import execute_messaging_boundary_call
from agent33.messaging.models import ChannelHealthResult, Message

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org"


class TelegramAdapter:
    """MessagingAdapter implementation for Telegram."""

    def __init__(self, token: str) -> None:
        self._token = token
        self._base = f"{_API_BASE}/bot{token}"
        self._client: httpx.AsyncClient | None = None
        self._queue: asyncio.Queue[Message] = asyncio.Queue()
        self._running = False
        self._poll_task: asyncio.Task[None] | None = None

    @property
    def platform(self) -> str:
        return "telegram"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start long-polling for updates."""
        self._client = httpx.AsyncClient(timeout=60)
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("TelegramAdapter started (long-poll)")

    async def stop(self) -> None:
        """Cancel polling and close the HTTP client."""
        self._running = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("TelegramAdapter stopped")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, channel_id: str, text: str) -> None:
        """Send a text message to a Telegram chat."""
        client = self._ensure_client()
        connector = "messaging:telegram"
        operation = "send"

        async def _perform_send(_request: object) -> httpx.Response:
            return await client.post(
                f"{self._base}/sendMessage",
                json={"chat_id": channel_id, "text": text, "parse_mode": "Markdown"},
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
        """Return the next queued inbound message."""
        return await self._queue.get()

    def enqueue_webhook_update(self, payload: dict[str, Any]) -> None:
        """Parse a Telegram webhook update and place it on the queue."""
        msg_data = payload.get("message") or payload.get("edited_message")
        if msg_data is None:
            return
        text = msg_data.get("text", "")
        chat = msg_data.get("chat", {})
        user = msg_data.get("from", {})
        self._queue.put_nowait(
            Message(
                platform="telegram",
                channel_id=str(chat.get("id", "")),
                user_id=str(user.get("id", "")),
                text=text,
                metadata={"raw": payload},
            )
        )

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> ChannelHealthResult:
        """Probe Telegram API via getMe and return health status."""
        if self._client is None:
            return ChannelHealthResult(
                platform="telegram",
                status="unavailable",
                detail="Adapter not started",
                queue_depth=self._queue.qsize(),
            )
        client = self._client
        assert client is not None
        start = time.monotonic()
        try:
            connector = "messaging:telegram"
            operation = "health_check"

            async def _perform_health_check(_request: object) -> httpx.Response:
                return await client.get(f"{self._base}/getMe")

            resp = await execute_messaging_boundary_call(
                connector=connector,
                operation=operation,
                payload={"endpoint": f"{self._base}/getMe"},
                metadata={"platform": self.platform},
                call=_perform_health_check,
                timeout_seconds=60.0,
            )
            latency = (time.monotonic() - start) * 1000
            if resp.status_code == 200 and resp.json().get("ok"):
                poll_alive = self._poll_task is not None and not self._poll_task.done()
                return ChannelHealthResult(
                    platform="telegram",
                    status="ok" if self._running and poll_alive else "degraded",
                    latency_ms=round(latency, 2),
                    detail="" if self._running and poll_alive else "Poll loop not running",
                    queue_depth=self._queue.qsize(),
                )
            return ChannelHealthResult(
                platform="telegram",
                status="degraded",
                latency_ms=round(latency, 2),
                detail=f"API returned status {resp.status_code}",
                queue_depth=self._queue.qsize(),
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ChannelHealthResult(
                platform="telegram",
                status="unavailable",
                latency_ms=round(latency, 2),
                detail=str(exc),
                queue_depth=self._queue.qsize(),
            )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Long-poll getUpdates in a background task."""
        offset = 0
        client = self._ensure_client()
        connector = "messaging:telegram"
        operation = "poll_updates"
        while self._running:
            try:

                async def _perform_poll(
                    _request: object,
                    *,
                    _offset: int = offset,
                    _client: httpx.AsyncClient = client,
                ) -> httpx.Response:
                    return await _client.get(
                        f"{self._base}/getUpdates",
                        params={"offset": _offset, "timeout": 30},
                    )

                resp = await execute_messaging_boundary_call(
                    connector=connector,
                    operation=operation,
                    payload={"offset": offset, "timeout": 30},
                    metadata={"platform": self.platform},
                    call=_perform_poll,
                    timeout_seconds=60.0,
                )
                resp.raise_for_status()
                updates = resp.json().get("result", [])
                for update in updates:
                    self.enqueue_webhook_update(update)
                    offset = update["update_id"] + 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram poll error")
                await asyncio.sleep(5)

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("TelegramAdapter is not started")
        return self._client
