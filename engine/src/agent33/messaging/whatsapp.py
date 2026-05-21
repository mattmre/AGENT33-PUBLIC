"""WhatsApp Cloud API adapter using plain httpx."""

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

_API_BASE = "https://graph.facebook.com/v18.0"


class WhatsAppAdapter:
    """MessagingAdapter implementation for WhatsApp via Meta Cloud API."""

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        verify_token: str,
        app_secret: str,
    ) -> None:
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._verify_token = verify_token
        self._app_secret = app_secret
        self._client: httpx.AsyncClient | None = None
        self._queue: asyncio.Queue[Message] = asyncio.Queue()

    @property
    def platform(self) -> str:
        return "whatsapp"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        logger.info("WhatsAppAdapter started")

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("WhatsAppAdapter stopped")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, channel_id: str, text: str) -> None:
        """Send a text message. *channel_id* is the recipient phone number."""
        client = self._ensure_client()
        connector = "messaging:whatsapp"
        operation = "send"

        async def _perform_send(_request: object) -> httpx.Response:
            return await client.post(
                f"{_API_BASE}/{self._phone_number_id}/messages",
                json={
                    "messaging_product": "whatsapp",
                    "to": channel_id,
                    "type": "text",
                    "text": {"body": text},
                },
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

    def enqueue_webhook_payload(self, payload: dict[str, Any]) -> None:
        """Parse a WhatsApp Cloud API webhook payload and enqueue messages."""
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])
                contact_map = {
                    c.get("wa_id", ""): c.get("profile", {}).get("name", "") for c in contacts
                }
                for msg in messages:
                    if msg.get("type") != "text":
                        continue
                    sender = msg.get("from", "")
                    self._queue.put_nowait(
                        Message(
                            platform="whatsapp",
                            channel_id=sender,
                            user_id=sender,
                            text=msg.get("text", {}).get("body", ""),
                            metadata={
                                "raw": msg,
                                "contact_name": contact_map.get(sender, ""),
                            },
                        )
                    )

    def verify_signature(self, signature: str, body: bytes) -> bool:
        """Verify the X-Hub-Signature-256 header."""
        expected = hmac.new(self._app_secret.encode(), body, hashlib.sha256).hexdigest()
        provided = signature.removeprefix("sha256=")
        return hmac.compare_digest(expected, provided)

    def verify_webhook_challenge(self, mode: str, token: str, challenge: str) -> str | None:
        """Return the challenge string if the verification token matches."""
        if mode == "subscribe" and token == self._verify_token:
            return challenge
        return None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> ChannelHealthResult:
        """Probe WhatsApp Cloud API via phone number info endpoint."""
        if self._client is None:
            return ChannelHealthResult(
                platform="whatsapp",
                status="unavailable",
                detail="Adapter not started",
                queue_depth=self._queue.qsize(),
            )
        client = self._client
        assert client is not None
        start = time.monotonic()
        try:
            connector = "messaging:whatsapp"
            operation = "health_check"

            async def _perform_health_check(_request: object) -> httpx.Response:
                return await client.get(
                    f"{_API_BASE}/{self._phone_number_id}",
                )

            resp = await execute_messaging_boundary_call(
                connector=connector,
                operation=operation,
                payload={"endpoint": f"{_API_BASE}/{self._phone_number_id}"},
                metadata={"platform": self.platform},
                call=_perform_health_check,
            )
            latency = (time.monotonic() - start) * 1000
            if resp.status_code == 200:
                return ChannelHealthResult(
                    platform="whatsapp",
                    status="ok",
                    latency_ms=round(latency, 2),
                    queue_depth=self._queue.qsize(),
                )
            return ChannelHealthResult(
                platform="whatsapp",
                status="degraded",
                latency_ms=round(latency, 2),
                detail=f"API returned status {resp.status_code}",
                queue_depth=self._queue.qsize(),
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ChannelHealthResult(
                platform="whatsapp",
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
            raise RuntimeError("WhatsAppAdapter is not started")
        return self._client
