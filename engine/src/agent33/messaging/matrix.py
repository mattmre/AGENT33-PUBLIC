"""Matrix channel adapter using Client-Server API v3 (raw httpx, no SDK).

Implements the :class:`MessagingAdapter` protocol with long-polling sync,
echo suppression, optional room filtering, and rate-limit handling.
E2EE is not implemented — plaintext rooms only.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from agent33.messaging.boundary import execute_messaging_boundary_call
from agent33.messaging.models import ChannelHealthResult, Message

logger = logging.getLogger(__name__)


class MatrixAdapter:
    """MessagingAdapter implementation for Matrix homeservers.

    Uses raw ``httpx.AsyncClient`` against the Matrix Client-Server API v3,
    consistent with the other adapters (Telegram, Discord, Slack, WhatsApp).

    Parameters
    ----------
    homeserver_url:
        Base URL of the Matrix homeserver (e.g. ``https://matrix.org``).
    access_token:
        Bearer token for the bot account.
    user_id:
        Full Matrix user ID (e.g. ``@agent33:matrix.org``).  Used for
        echo suppression.
    allowed_room_ids:
        Optional whitelist of room IDs to process events from.  If
        ``None``, events from all joined rooms are processed.
    sync_timeout_ms:
        Long-poll timeout in milliseconds for ``/sync`` (default 30 000).
    """

    def __init__(
        self,
        homeserver_url: str,
        access_token: str,
        user_id: str,
        allowed_room_ids: list[str] | None = None,
        sync_timeout_ms: int = 30_000,
    ) -> None:
        self._homeserver_url = homeserver_url.rstrip("/")
        self._access_token = access_token
        self._user_id = user_id
        self._allowed_room_ids = set(allowed_room_ids) if allowed_room_ids else None
        self._sync_timeout_ms = sync_timeout_ms

        self._client: httpx.AsyncClient | None = None
        self._queue: asyncio.Queue[Message] = asyncio.Queue()
        self._running = False
        self._next_batch: str | None = None
        self._txn_counter = 0
        self._sync_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def platform(self) -> str:
        return "matrix"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Create HTTP client and start the background sync loop."""
        self._client = httpx.AsyncClient(
            base_url=self._homeserver_url,
            headers={"Authorization": f"Bearer {self._access_token}"},
            timeout=httpx.Timeout(self._sync_timeout_ms / 1000 + 10),
        )
        self._running = True
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("MatrixAdapter started (long-poll sync)")

    async def stop(self) -> None:
        """Cancel the sync loop and close the HTTP client."""
        self._running = False
        if self._sync_task is not None:
            self._sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sync_task
            self._sync_task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        logger.info("MatrixAdapter stopped")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send(self, channel_id: str, text: str) -> None:
        """Send a text message to a Matrix room.

        Uses a monotonically increasing transaction ID for idempotency.
        Retries once on HTTP 429 (rate-limited).
        """
        client = self._ensure_client()
        self._txn_counter += 1
        txn_id = f"agent33_{self._txn_counter}_{int(time.time() * 1000)}"
        body = {"msgtype": "m.text", "body": text}
        encoded_channel_id = quote(channel_id, safe="")
        encoded_txn_id = quote(txn_id, safe="")
        path = (
            f"/_matrix/client/v3/rooms/{encoded_channel_id}/send/m.room.message/{encoded_txn_id}"
        )

        connector = "messaging:matrix"
        operation = "send"

        async def _perform_send(_request: object) -> httpx.Response:
            resp = await client.put(path, json=body)
            if resp.status_code == 429:
                retry_ms = resp.json().get("retry_after_ms", 5000)
                await asyncio.sleep(retry_ms / 1000)
                resp = await client.put(path, json=body)
            return resp

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
        """Block until the next inbound message is available and return it."""
        return await self._queue.get()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health_check(self) -> ChannelHealthResult:
        """Probe the homeserver via ``/account/whoami`` and return health."""
        if self._client is None:
            return ChannelHealthResult(
                platform="matrix",
                status="unavailable",
                detail="Adapter not started",
                queue_depth=self._queue.qsize(),
            )
        client = self._client
        assert client is not None

        start = time.monotonic()
        try:
            connector = "messaging:matrix"
            operation = "health_check"

            async def _perform_health_check(_request: object) -> httpx.Response:
                return await client.get("/_matrix/client/v3/account/whoami")

            resp = await execute_messaging_boundary_call(
                connector=connector,
                operation=operation,
                payload={"endpoint": "/_matrix/client/v3/account/whoami"},
                metadata={"platform": self.platform},
                call=_perform_health_check,
            )
            latency = (time.monotonic() - start) * 1000

            if resp.status_code == 200:
                sync_alive = self._sync_task is not None and not self._sync_task.done()
                queue_depth = self._queue.qsize()
                if self._running and sync_alive:
                    status = "ok" if queue_depth < 100 else "degraded"
                    detail = (
                        f"Connected as {self._user_id}"
                        if status == "ok"
                        else f"Queue depth {queue_depth} >= 100"
                    )
                else:
                    status = "degraded"
                    detail = "Sync loop not running"
                return ChannelHealthResult(
                    platform="matrix",
                    status=status,
                    latency_ms=round(latency, 2),
                    detail=detail,
                    queue_depth=queue_depth,
                )

            return ChannelHealthResult(
                platform="matrix",
                status="degraded",
                latency_ms=round(latency, 2),
                detail=f"API returned status {resp.status_code}",
                queue_depth=self._queue.qsize(),
            )
        except Exception as exc:
            latency = (time.monotonic() - start) * 1000
            return ChannelHealthResult(
                platform="matrix",
                status="unavailable",
                latency_ms=round(latency, 2),
                detail=str(exc),
                queue_depth=self._queue.qsize(),
            )

    # ------------------------------------------------------------------
    # Internal — sync loop
    # ------------------------------------------------------------------

    async def _sync_loop(self) -> None:
        """Background task that long-polls ``/_matrix/client/v3/sync``."""
        connector = "messaging:matrix"
        operation = "sync_loop"
        while self._running:
            try:
                params: dict[str, str] = {"timeout": str(self._sync_timeout_ms)}
                if self._next_batch:
                    params["since"] = self._next_batch

                client = self._ensure_client()
                frozen_params = params.copy()

                async def _perform_sync(
                    _request: object,
                    *,
                    _client: httpx.AsyncClient = client,
                    _params: dict[str, str] = frozen_params,
                ) -> httpx.Response:
                    return await _client.get("/_matrix/client/v3/sync", params=_params)

                resp = await execute_messaging_boundary_call(
                    connector=connector,
                    operation=operation,
                    payload={"timeout_ms": self._sync_timeout_ms, "since": self._next_batch or ""},
                    metadata={"platform": self.platform},
                    call=_perform_sync,
                    timeout_seconds=(self._sync_timeout_ms / 1000) + 10,
                )

                if resp.status_code == 429:
                    retry_ms = resp.json().get("retry_after_ms", 5000)
                    await asyncio.sleep(retry_ms / 1000)
                    continue

                resp.raise_for_status()
                data = resp.json()

                self._next_batch = data.get("next_batch")
                self._process_sync_response(data)

            except (httpx.TimeoutException, TimeoutError):
                continue  # Normal for long-polling
            except RuntimeError as exc:
                if isinstance(exc.__cause__, (TimeoutError, httpx.TimeoutException)):
                    continue  # Boundary-wrapped long-poll timeout
                logger.exception("Matrix sync error")
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Matrix sync error")
                await asyncio.sleep(5)

    def _process_sync_response(self, data: dict[str, Any]) -> None:
        """Extract text messages from a sync response and enqueue them."""
        rooms = data.get("rooms", {}).get("join", {})
        for room_id, room_data in rooms.items():
            # Room filtering
            if self._allowed_room_ids and room_id not in self._allowed_room_ids:
                continue

            timeline = room_data.get("timeline", {}).get("events", [])
            for event in timeline:
                if event.get("type") != "m.room.message":
                    continue
                # Echo suppression
                if event.get("sender") == self._user_id:
                    continue

                content = event.get("content", {})
                if content.get("msgtype") != "m.text":
                    continue

                ts = event.get("origin_server_ts", 0)
                message = Message(
                    platform="matrix",
                    channel_id=room_id,
                    user_id=event.get("sender", ""),
                    text=content.get("body", ""),
                    timestamp=datetime.fromtimestamp(ts / 1000, tz=UTC),
                    metadata={"event_id": event.get("event_id", "")},
                )
                self._queue.put_nowait(message)

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("MatrixAdapter is not started")
        return self._client
