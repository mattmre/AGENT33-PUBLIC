"""Tests for the P2.6 WebSocket streaming client library.

Exercises URL building, connection lifecycle, event parsing, retry logic,
error handling, and the async-context-manager interface -- all without
requiring a live WebSocket server.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent33.client.streaming_client import StreamEvent, StreamingClient, StreamingClientError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:8000"
TOKEN = "test-jwt-token-abc123"
AGENT_ID = "code-worker"


def _make_event(event: str, data: dict[str, Any], seq: int) -> str:
    """Return a JSON-encoded StreamEvent string."""
    return json.dumps(
        {
            "event": event,
            "data": data,
            "seq": seq,
            "timestamp": "2026-03-24T00:00:00+00:00",
        }
    )


class _AsyncIter:
    """Wraps a list of messages into an async iterator for mock WebSockets."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = messages
        self._index = 0

    def __aiter__(self) -> _AsyncIter:
        return self

    async def __anext__(self) -> str:
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        msg = self._messages[self._index]
        self._index += 1
        return msg


def _mock_ws(messages: list[str] | None = None) -> MagicMock:
    """Build a mock ClientConnection that yields *messages* on iteration.

    Uses MagicMock so that __aiter__ / __anext__ dispatch correctly.
    """
    ws = MagicMock()
    ws.close_code = None  # connection open
    ws.send = AsyncMock()
    ws.close = AsyncMock()

    msg_list = messages if messages is not None else []
    iterator = _AsyncIter(msg_list)
    ws.__aiter__ = MagicMock(return_value=iterator)

    return ws


# ===================================================================
# URL building
# ===================================================================


class TestWsUrl:
    """Tests for StreamingClient.ws_url()."""

    def test_http_to_ws(self) -> None:
        client = StreamingClient(base_url="http://example.com", token=TOKEN, agent_id=AGENT_ID)
        url = client.ws_url()
        assert url.startswith("ws://example.com")

    def test_https_to_wss(self) -> None:
        client = StreamingClient(base_url="https://example.com", token=TOKEN, agent_id=AGENT_ID)
        url = client.ws_url()
        assert url.startswith("wss://example.com")

    def test_includes_token_query_param(self) -> None:
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        url = client.ws_url()
        assert f"?token={TOKEN}" in url

    def test_includes_agent_id_in_path(self) -> None:
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        url = client.ws_url()
        assert f"/v1/stream/agent/{AGENT_ID}" in url

    def test_full_url_structure(self) -> None:
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        url = client.ws_url()
        expected = f"ws://localhost:8000/v1/stream/agent/{AGENT_ID}?token={TOKEN}"
        assert url == expected

    def test_trailing_slash_stripped(self) -> None:
        client = StreamingClient(base_url="http://example.com/", token=TOKEN, agent_id=AGENT_ID)
        url = client.ws_url()
        assert "//" not in url.split("://", 1)[1]  # no double slashes in path

    def test_ws_url_passthrough(self) -> None:
        """If the base_url already uses ws://, leave it as-is."""
        client = StreamingClient(base_url="ws://host:9000", token=TOKEN, agent_id=AGENT_ID)
        url = client.ws_url()
        assert url.startswith("ws://host:9000/v1/stream/agent/")

    def test_wss_url_passthrough(self) -> None:
        """If the base_url already uses wss://, leave it as-is."""
        client = StreamingClient(base_url="wss://host:9000", token=TOKEN, agent_id=AGENT_ID)
        url = client.ws_url()
        assert url.startswith("wss://host:9000/v1/stream/agent/")


# ===================================================================
# Connection lifecycle
# ===================================================================


class TestConnect:
    """Tests for connect(), is_connected, and close()."""

    async def test_connect_yields_stream_events(self) -> None:
        """connect() should yield StreamEvent objects parsed from JSON."""
        messages = [
            _make_event("thinking", {"status": "processing"}, 1),
            _make_event("response", {"output": "hello"}, 2),
            _make_event("done", {}, 3),
        ]
        mock_ws = _mock_ws(messages)

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            return_value=_async_return(mock_ws),
        ):
            async with client.connect() as events:
                collected = [ev async for ev in events]

        assert len(collected) == 3
        assert collected[0].event == "thinking"
        assert collected[1].event == "response"
        assert collected[1].data == {"output": "hello"}
        assert collected[2].event == "done"

    async def test_connect_parses_json_into_stream_event(self) -> None:
        """Each yielded object is a StreamEvent with all fields populated."""
        raw = _make_event("tool_call", {"tool": "shell", "args": ["ls"]}, 5)
        mock_ws = _mock_ws([raw])

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            return_value=_async_return(mock_ws),
        ):
            async with client.connect() as events:
                ev = await events.__anext__()

        assert isinstance(ev, StreamEvent)
        assert ev.seq == 5
        assert ev.data["tool"] == "shell"
        assert ev.timestamp == "2026-03-24T00:00:00+00:00"

    async def test_connect_stops_on_close(self) -> None:
        """When the server closes the connection normally, iteration ends."""
        mock_ws = _mock_ws([])  # empty stream
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            return_value=_async_return(mock_ws),
        ):
            async with client.connect() as events:
                collected = [ev async for ev in events]

        assert collected == []

    async def test_is_connected_true_after_connect(self) -> None:
        mock_ws = _mock_ws([])
        mock_ws.close_code = None  # open
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            return_value=_async_return(mock_ws),
        ):
            async with client.connect():
                assert client.is_connected is True

    async def test_is_connected_false_after_close(self) -> None:
        mock_ws = _mock_ws([])
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            return_value=_async_return(mock_ws),
        ):
            async with client.connect():
                pass
        # After exiting context manager, close() was called.
        assert client.is_connected is False

    async def test_is_connected_false_before_connect(self) -> None:
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        assert client.is_connected is False


# ===================================================================
# Send
# ===================================================================


class TestSend:
    """Tests for send()."""

    async def test_send_json_data(self) -> None:
        """send() should JSON-encode the dict and send it over the WS."""
        mock_ws = _mock_ws([])
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            return_value=_async_return(mock_ws),
        ):
            async with client.connect():
                await client.send({"input": "hello", "context": {}})

        mock_ws.send.assert_awaited_once()
        sent_payload = mock_ws.send.call_args[0][0]
        parsed = json.loads(sent_payload)
        assert parsed == {"input": "hello", "context": {}}

    async def test_send_raises_when_not_connected(self) -> None:
        """send() should raise StreamingClientError if not connected."""
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with pytest.raises(StreamingClientError, match="Not connected"):
            await client.send({"input": "test"})


# ===================================================================
# Close
# ===================================================================


class TestClose:
    """Tests for close()."""

    async def test_close_calls_ws_close(self) -> None:
        mock_ws = _mock_ws([])
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            return_value=_async_return(mock_ws),
        ):
            async with client.connect():
                pass

        # The context manager calls close() on exit.
        mock_ws.close.assert_awaited_once()

    async def test_close_idempotent(self) -> None:
        """Calling close() multiple times should not raise."""
        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        # close() when not connected is a no-op.
        await client.close()
        await client.close()


# ===================================================================
# Retry logic
# ===================================================================


class TestRetry:
    """Tests for connection retry behaviour."""

    async def test_retries_on_connection_refused(self) -> None:
        """connect() retries up to max_retries on ConnectionRefusedError."""
        call_count = 0
        success_ws = _mock_ws([_make_event("done", {}, 1)])

        def _failing_connect(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionRefusedError("Connection refused")
            fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
            fut.set_result(success_ws)
            return fut

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            side_effect=_failing_connect,
        ):
            async with client.connect(max_retries=3, retry_delay_seconds=0.01) as events:
                collected = [ev async for ev in events]

        assert call_count == 3
        assert len(collected) == 1

    async def test_raises_after_exhausting_retries(self) -> None:
        """connect() raises StreamingClientError after max_retries + 1 failures."""

        def _always_fail(*args: Any, **kwargs: Any) -> Any:
            raise ConnectionRefusedError("Connection refused")

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with (
            patch(
                "agent33.client.streaming_client.connect",
                side_effect=_always_fail,
            ),
            pytest.raises(StreamingClientError, match="Failed to connect after 4 attempts"),
        ):
            async with client.connect(max_retries=3, retry_delay_seconds=0.01) as _events:
                pass  # pragma: no cover -- never reached

    async def test_no_retry_on_zero_max_retries(self) -> None:
        """With max_retries=0, only one attempt is made."""
        call_count = 0

        def _fail(*args: Any, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            raise ConnectionRefusedError("refused")

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with (
            patch(
                "agent33.client.streaming_client.connect",
                side_effect=_fail,
            ),
            pytest.raises(StreamingClientError, match="Failed to connect after 1 attempts"),
        ):
            async with client.connect(max_retries=0, retry_delay_seconds=0.01) as _events:
                pass  # pragma: no cover

        assert call_count == 1


# ===================================================================
# Error handling
# ===================================================================


class TestErrorHandling:
    """Tests for unexpected disconnection and malformed messages."""

    async def test_unexpected_disconnect_raises(self) -> None:
        """An abnormal server close should raise StreamingClientError."""
        from websockets.exceptions import ConnectionClosedError as WsClosedError
        from websockets.frames import Close

        mock_ws = MagicMock()
        mock_ws.close_code = None
        mock_ws.send = AsyncMock()
        mock_ws.close = AsyncMock()

        class _ExplodingIter:
            def __aiter__(self) -> _ExplodingIter:
                return self

            async def __anext__(self) -> str:
                raise WsClosedError(
                    rcvd=Close(code=1006, reason="abnormal"),
                    sent=None,
                )

        mock_ws.__aiter__ = MagicMock(return_value=_ExplodingIter())

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with (
            patch(
                "agent33.client.streaming_client.connect",
                return_value=_async_return(mock_ws),
            ),
            pytest.raises(StreamingClientError, match="Server closed connection"),
        ):
            async with client.connect() as events:
                async for _ev in events:
                    pass  # pragma: no cover

    async def test_invalid_json_from_server(self) -> None:
        """Non-JSON messages from the server raise StreamingClientError."""
        mock_ws = _mock_ws(["not valid json {{{"])

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with (
            patch(
                "agent33.client.streaming_client.connect",
                return_value=_async_return(mock_ws),
            ),
            pytest.raises(StreamingClientError, match="Invalid JSON"),
        ):
            async with client.connect() as events:
                async for _ev in events:
                    pass  # pragma: no cover


# ===================================================================
# Sequential event ordering
# ===================================================================


class TestSequentialEvents:
    """Tests for correct seq number propagation."""

    async def test_incrementing_seq_numbers(self) -> None:
        """Events should preserve the seq values from the server."""
        messages = [
            _make_event("thinking", {}, 1),
            _make_event("tool_call", {"tool": "shell"}, 2),
            _make_event("response", {"output": "ok"}, 3),
            _make_event("done", {}, 4),
        ]
        mock_ws = _mock_ws(messages)

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            return_value=_async_return(mock_ws),
        ):
            async with client.connect() as events:
                seqs = [ev.seq async for ev in events]

        assert seqs == [1, 2, 3, 4]


# ===================================================================
# StreamEvent model
# ===================================================================


class TestStreamEventModel:
    """Tests for the StreamEvent Pydantic model."""

    def test_from_dict(self) -> None:
        ev = StreamEvent(event="response", data={"key": "val"}, seq=1)
        assert ev.event == "response"
        assert ev.data == {"key": "val"}
        assert ev.seq == 1

    def test_default_data(self) -> None:
        ev = StreamEvent(event="done", seq=2)
        assert ev.data == {}

    def test_default_timestamp(self) -> None:
        ev = StreamEvent(event="done", seq=2)
        assert ev.timestamp == ""


# ===================================================================
# Async context manager protocol
# ===================================================================


class TestAsyncContextManager:
    """Verify connect() works as an async context manager."""

    async def test_async_with_protocol(self) -> None:
        """Verify 'async with client.connect() as events' works."""
        mock_ws = _mock_ws([_make_event("done", {}, 1)])

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with patch(
            "agent33.client.streaming_client.connect",
            return_value=_async_return(mock_ws),
        ):
            async with client.connect(max_retries=0) as events:
                collected = [ev async for ev in events]
                assert len(collected) == 1
                assert collected[0].event == "done"

        # After exit, connection is cleaned up.
        assert client.is_connected is False

    async def test_context_manager_cleans_up_on_exception(self) -> None:
        """If an exception occurs inside 'async with', close() is still called."""
        mock_ws = _mock_ws([_make_event("thinking", {}, 1)])

        client = StreamingClient(base_url=BASE_URL, token=TOKEN, agent_id=AGENT_ID)
        with (
            patch(
                "agent33.client.streaming_client.connect",
                return_value=_async_return(mock_ws),
            ),
            pytest.raises(RuntimeError, match="boom"),
        ):
            async with client.connect() as _events:
                raise RuntimeError("boom")

        # close() was called despite the exception.
        mock_ws.close.assert_awaited_once()
        assert client.is_connected is False


# ---------------------------------------------------------------------------
# Test utilities
# ---------------------------------------------------------------------------


def _async_return(value: Any) -> Any:
    """Create a coroutine-like object that connect() can await.

    ``websockets.connect()`` is a callable that returns an awaitable;
    we simulate that by returning a coroutine that resolves to *value*.
    """
    fut: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
    fut.set_result(value)
    return fut
