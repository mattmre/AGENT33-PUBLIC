"""WebSocket streaming client for consuming real-time agent invocation events.

P2.6 -- Provides a Python client library that connects to the P2.5 WebSocket
streaming endpoint and yields ``StreamEvent`` objects as they arrive.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, Field
from websockets import ConnectionClosedError, ConnectionClosedOK
from websockets.asyncio.client import ClientConnection, connect

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared event model (mirrors server-side StreamEvent)
# ---------------------------------------------------------------------------


class StreamEvent(BaseModel):
    """A single streaming event received from the WebSocket connection."""

    event: str = Field(description="Event type: thinking, tool_call, response, error, done")
    data: dict[str, Any] = Field(default_factory=dict)
    seq: int = Field(description="Monotonically increasing sequence number")
    timestamp: str = Field(default="", description="ISO 8601 timestamp")


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class StreamingClientError(Exception):
    """Raised when the streaming client encounters a connection error."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class StreamingClient:
    """Async WebSocket client for consuming agent streaming events.

    Usage::

        client = StreamingClient(
            base_url="http://localhost:8000",
            token="<jwt>",
            agent_id="code-worker",
        )
        async with client.connect() as events:
            async for event in events:
                print(event.event, event.data)
    """

    def __init__(self, base_url: str, token: str, agent_id: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._agent_id = agent_id
        self._ws: ClientConnection | None = None

    # -- URL builder --------------------------------------------------------

    def ws_url(self) -> str:
        """Build the WebSocket URL for the streaming endpoint.

        Converts ``http://`` to ``ws://`` and ``https://`` to ``wss://``,
        appends the agent path, and includes the JWT as a query parameter.
        """
        url = self._base_url
        if url.startswith("https://"):
            url = "wss://" + url[len("https://") :]
        elif url.startswith("http://"):
            url = "ws://" + url[len("http://") :]
        # If it already starts with ws:// or wss://, leave it alone.
        return f"{url}/v1/stream/agent/{self._agent_id}?token={self._token}"

    # -- Connection state ---------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Return ``True`` if the WebSocket connection is open."""
        if self._ws is None:
            return False
        try:
            # websockets 12+ exposes .close_code; a non-None value means closed.
            return self._ws.close_code is None
        except AttributeError:  # pragma: no cover
            return False

    # -- Send / close -------------------------------------------------------

    async def send(self, data: dict[str, Any]) -> None:
        """Send a JSON-encoded message to the server.

        Raises ``StreamingClientError`` if the connection is not open.
        """
        if self._ws is None:
            raise StreamingClientError("Not connected")
        try:
            await self._ws.send(json.dumps(data))
        except Exception as exc:
            raise StreamingClientError(f"Failed to send message: {exc}") from exc

    async def close(self) -> None:
        """Close the WebSocket connection cleanly."""
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                logger.debug("streaming_client_close_error", exc_info=True)

    # -- Connect / iterate --------------------------------------------------

    def connect(
        self,
        max_retries: int = 3,
        retry_delay_seconds: float = 1.0,
    ) -> _StreamContext:
        """Return an async context manager that yields a ``StreamEvent`` iterator.

        On connection errors the client retries up to *max_retries* times with
        a *retry_delay_seconds* pause between attempts.  If all retries are
        exhausted a ``StreamingClientError`` is raised.
        """
        return _StreamContext(self, max_retries, retry_delay_seconds)

    async def _open(
        self,
        max_retries: int,
        retry_delay_seconds: float,
    ) -> None:
        """Establish the WebSocket connection with retry logic."""
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                self._ws = await connect(self.ws_url())
                return
            except Exception as exc:
                last_exc = exc
                logger.debug(
                    "streaming_client_connect_retry attempt=%d max_retries=%d",
                    attempt + 1,
                    max_retries,
                )
                if attempt < max_retries:
                    await asyncio.sleep(retry_delay_seconds)

        raise StreamingClientError(
            f"Failed to connect after {max_retries + 1} attempts: {last_exc}"
        ) from last_exc

    async def _iter_events(self) -> AsyncIterator[StreamEvent]:
        """Yield ``StreamEvent`` objects from the open WebSocket connection."""
        if self._ws is None:
            raise StreamingClientError("Not connected")

        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, TypeError) as exc:
                    raise StreamingClientError(f"Invalid JSON from server: {exc}") from exc
                yield StreamEvent.model_validate(payload)
        except ConnectionClosedOK:
            # Server closed the connection normally (e.g. after "done" event).
            return
        except ConnectionClosedError as exc:
            raise StreamingClientError(f"Server closed connection unexpectedly: {exc}") from exc


# ---------------------------------------------------------------------------
# Async context manager returned by connect()
# ---------------------------------------------------------------------------


class _StreamContext:
    """Async context manager that opens the WebSocket and yields events."""

    def __init__(
        self,
        client: StreamingClient,
        max_retries: int,
        retry_delay_seconds: float,
    ) -> None:
        self._client = client
        self._max_retries = max_retries
        self._retry_delay_seconds = retry_delay_seconds

    async def __aenter__(self) -> AsyncIterator[StreamEvent]:
        await self._client._open(self._max_retries, self._retry_delay_seconds)
        return self._client._iter_events()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self._client.close()

    # Also support direct iteration (async for event in client.connect(...)):
    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> StreamEvent:
        raise TypeError(
            "StreamingClient.connect() returns a context manager. "
            "Use 'async with client.connect() as events:' instead."
        )
