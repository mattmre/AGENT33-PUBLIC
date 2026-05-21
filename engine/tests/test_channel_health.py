"""Tests for channel health check system.

Tests cover: ChannelHealthResult model, per-adapter health_check() methods,
health route integration with channels, and the dedicated /health/channels
endpoint.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agent33.messaging.models import ChannelHealthResult

# ═══════════════════════════════════════════════════════════════════════
# ChannelHealthResult Model Tests
# ═══════════════════════════════════════════════════════════════════════


class TestChannelHealthResult:
    """Test the ChannelHealthResult Pydantic model."""

    def test_ok_result(self) -> None:
        result = ChannelHealthResult(
            platform="telegram",
            status="ok",
            latency_ms=42.5,
            queue_depth=3,
        )
        assert result.platform == "telegram"
        assert result.status == "ok"
        assert result.latency_ms == 42.5
        assert result.queue_depth == 3
        assert result.detail == ""

    def test_unavailable_result(self) -> None:
        result = ChannelHealthResult(
            platform="discord",
            status="unavailable",
            detail="Adapter not started",
        )
        assert result.status == "unavailable"
        assert result.detail == "Adapter not started"
        assert result.latency_ms is None
        assert result.queue_depth == 0

    def test_degraded_result(self) -> None:
        result = ChannelHealthResult(
            platform="slack",
            status="degraded",
            latency_ms=1500.0,
            detail="API returned status 503",
        )
        assert result.status == "degraded"
        assert result.latency_ms == 1500.0

    def test_serialization_roundtrip(self) -> None:
        result = ChannelHealthResult(
            platform="whatsapp",
            status="ok",
            latency_ms=88.0,
            queue_depth=5,
        )
        data = result.model_dump()
        restored = ChannelHealthResult.model_validate(data)
        assert restored == result

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError):
            ChannelHealthResult(
                platform="test",
                status="broken",  # type: ignore[arg-type]
            )


# ═══════════════════════════════════════════════════════════════════════
# Telegram Adapter Health Check Tests
# ═══════════════════════════════════════════════════════════════════════


class TestTelegramHealthCheck:
    """Test TelegramAdapter.health_check()."""

    def _make_adapter(self) -> Any:
        from agent33.messaging.telegram import TelegramAdapter

        return TelegramAdapter(token="test-token")

    @pytest.mark.asyncio
    async def test_not_started(self) -> None:
        adapter = self._make_adapter()
        result = await adapter.health_check()
        assert result.status == "unavailable"
        assert "not started" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_ok_with_poll_running(self) -> None:
        adapter = self._make_adapter()
        # Simulate started state
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"id": 123}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        adapter._client = mock_client
        adapter._running = True
        # Simulate live poll task
        adapter._poll_task = MagicMock()
        adapter._poll_task.done.return_value = False

        result = await adapter.health_check()
        assert result.status == "ok"
        assert result.latency_ms is not None
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_degraded_poll_not_running(self) -> None:
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"id": 123}}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        adapter._client = mock_client
        adapter._running = False  # poll stopped
        adapter._poll_task = None

        result = await adapter.health_check()
        assert result.status == "degraded"
        assert "poll" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_degraded_on_bad_status(self) -> None:
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"ok": False}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "degraded"
        assert "401" in result.detail

    @pytest.mark.asyncio
    async def test_unavailable_on_network_error(self) -> None:
        adapter = self._make_adapter()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "unavailable"
        assert "connection refused" in result.detail.lower()

    @pytest.mark.asyncio
    async def test_queue_depth_reported(self) -> None:
        adapter = self._make_adapter()
        # Put something in the queue
        from agent33.messaging.models import Message

        adapter._queue.put_nowait(
            Message(platform="telegram", channel_id="1", user_id="1", text="hi")
        )
        result = await adapter.health_check()
        assert result.queue_depth == 1


# ═══════════════════════════════════════════════════════════════════════
# Discord Adapter Health Check Tests
# ═══════════════════════════════════════════════════════════════════════


class TestDiscordHealthCheck:
    """Test DiscordAdapter.health_check()."""

    def _make_adapter(self) -> Any:
        from agent33.messaging.discord import DiscordAdapter

        return DiscordAdapter(bot_token="test-token", public_key="aa" * 32)

    @pytest.mark.asyncio
    async def test_not_started(self) -> None:
        adapter = self._make_adapter()
        result = await adapter.health_check()
        assert result.status == "unavailable"
        assert result.platform == "discord"

    @pytest.mark.asyncio
    async def test_ok(self) -> None:
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "ok"
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_degraded(self) -> None:
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 502

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "degraded"
        assert "502" in result.detail

    @pytest.mark.asyncio
    async def test_unavailable_on_error(self) -> None:
        adapter = self._make_adapter()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "unavailable"


# ═══════════════════════════════════════════════════════════════════════
# Slack Adapter Health Check Tests
# ═══════════════════════════════════════════════════════════════════════


class TestSlackHealthCheck:
    """Test SlackAdapter.health_check()."""

    def _make_adapter(self) -> Any:
        from agent33.messaging.slack import SlackAdapter

        return SlackAdapter(bot_token="xoxb-test", signing_secret="secret")

    @pytest.mark.asyncio
    async def test_not_started(self) -> None:
        adapter = self._make_adapter()
        result = await adapter.health_check()
        assert result.status == "unavailable"
        assert result.platform == "slack"

    @pytest.mark.asyncio
    async def test_ok(self) -> None:
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "team": "test"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_degraded_auth_test_fails(self) -> None:
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": False, "error": "invalid_auth"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "degraded"
        assert "invalid_auth" in result.detail

    @pytest.mark.asyncio
    async def test_unavailable_on_error(self) -> None:
        adapter = self._make_adapter()
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "unavailable"


# ═══════════════════════════════════════════════════════════════════════
# WhatsApp Adapter Health Check Tests
# ═══════════════════════════════════════════════════════════════════════


class TestWhatsAppHealthCheck:
    """Test WhatsAppAdapter.health_check()."""

    def _make_adapter(self) -> Any:
        from agent33.messaging.whatsapp import WhatsAppAdapter

        return WhatsAppAdapter(
            access_token="test-token",
            phone_number_id="123456",
            verify_token="verify",
            app_secret="secret",
        )

    @pytest.mark.asyncio
    async def test_not_started(self) -> None:
        adapter = self._make_adapter()
        result = await adapter.health_check()
        assert result.status == "unavailable"
        assert result.platform == "whatsapp"

    @pytest.mark.asyncio
    async def test_ok(self) -> None:
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "ok"
        assert result.latency_ms is not None

    @pytest.mark.asyncio
    async def test_degraded(self) -> None:
        adapter = self._make_adapter()
        mock_response = MagicMock()
        mock_response.status_code = 403

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "degraded"
        assert "403" in result.detail

    @pytest.mark.asyncio
    async def test_unavailable_on_error(self) -> None:
        adapter = self._make_adapter()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ReadTimeout("timeout"))
        adapter._client = mock_client

        result = await adapter.health_check()
        assert result.status == "unavailable"


# ═══════════════════════════════════════════════════════════════════════
# Health Route Integration Tests
# ═══════════════════════════════════════════════════════════════════════


class TestHealthRouteChannelIntegration:
    """Test that channels appear in aggregate /health and /health/channels."""

    @pytest.mark.asyncio
    async def test_health_includes_channel_status(self) -> None:
        """Registered channels appear in /health response."""
        mock_adapter = AsyncMock()
        mock_adapter.health_check.return_value = ChannelHealthResult(
            platform="telegram", status="ok", latency_ms=50.0
        )

        with patch(
            "agent33.api.routes.health._get_adapters",
            return_value={"telegram": mock_adapter},
        ):
            from agent33.api.routes.health import health

            result = await health()
            assert "channel:telegram" in result["services"]
            assert result["services"]["channel:telegram"] == "ok"

    @pytest.mark.asyncio
    async def test_health_degraded_when_channel_down(self) -> None:
        """Aggregate status is degraded when a channel is unavailable."""
        mock_adapter = AsyncMock()
        mock_adapter.health_check.return_value = ChannelHealthResult(
            platform="discord", status="unavailable", detail="not started"
        )

        with patch(
            "agent33.api.routes.health._get_adapters",
            return_value={"discord": mock_adapter},
        ):
            from agent33.api.routes.health import health

            result = await health()
            assert result["services"]["channel:discord"] == "unavailable"
            # Note: overall status depends on all checks, but channel being
            # unavailable contributes to degraded
            assert result["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_channels_endpoint(self) -> None:
        """The /health/channels endpoint returns detailed per-channel info."""
        mock_adapter = AsyncMock()
        mock_adapter.health_check.return_value = ChannelHealthResult(
            platform="slack",
            status="ok",
            latency_ms=120.5,
            queue_depth=2,
        )

        with patch(
            "agent33.api.routes.health._get_adapters",
            return_value={"slack": mock_adapter},
        ):
            from agent33.api.routes.health import channel_health

            result = await channel_health()
            assert "channels" in result
            assert "slack" in result["channels"]
            slack = result["channels"]["slack"]
            assert slack["status"] == "ok"
            assert slack["latency_ms"] == 120.5
            assert slack["queue_depth"] == 2

    @pytest.mark.asyncio
    async def test_health_channels_handles_exception(self) -> None:
        """Channel health endpoint handles adapter exceptions gracefully."""
        mock_adapter = AsyncMock()
        mock_adapter.health_check.side_effect = RuntimeError("unexpected error")

        with patch(
            "agent33.api.routes.health._get_adapters",
            return_value={"broken": mock_adapter},
        ):
            from agent33.api.routes.health import channel_health

            result = await channel_health()
            assert result["channels"]["broken"]["status"] == "unavailable"
            assert "unexpected error" in result["channels"]["broken"]["detail"]

    @pytest.mark.asyncio
    async def test_no_channels_registered(self) -> None:
        """Health endpoints work fine with no channels registered."""
        with patch(
            "agent33.api.routes.health._get_adapters",
            return_value={},
        ):
            from agent33.api.routes.health import channel_health

            result = await channel_health()
            assert result["channels"] == {}


# ═══════════════════════════════════════════════════════════════════════
# Protocol Compliance Tests
# ═══════════════════════════════════════════════════════════════════════


class TestMessagingAdapterProtocol:
    """Test that all adapters still satisfy the MessagingAdapter protocol."""

    def test_telegram_is_messaging_adapter(self) -> None:
        from agent33.messaging.base import MessagingAdapter
        from agent33.messaging.telegram import TelegramAdapter

        adapter = TelegramAdapter(token="test")
        assert isinstance(adapter, MessagingAdapter)

    def test_discord_is_messaging_adapter(self) -> None:
        from agent33.messaging.base import MessagingAdapter
        from agent33.messaging.discord import DiscordAdapter

        adapter = DiscordAdapter(bot_token="test", public_key="aa" * 32)
        assert isinstance(adapter, MessagingAdapter)

    def test_slack_is_messaging_adapter(self) -> None:
        from agent33.messaging.base import MessagingAdapter
        from agent33.messaging.slack import SlackAdapter

        adapter = SlackAdapter(bot_token="test", signing_secret="secret")
        assert isinstance(adapter, MessagingAdapter)

    def test_whatsapp_is_messaging_adapter(self) -> None:
        from agent33.messaging.base import MessagingAdapter
        from agent33.messaging.whatsapp import WhatsAppAdapter

        adapter = WhatsAppAdapter(
            access_token="test",
            phone_number_id="123",
            verify_token="verify",
            app_secret="secret",
        )
        assert isinstance(adapter, MessagingAdapter)
