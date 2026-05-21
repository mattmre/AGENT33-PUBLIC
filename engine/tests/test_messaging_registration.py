"""Tests for POST /v1/connectors/messaging/register and GET /v1/connectors/messaging/status."""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agent33.main import app
from agent33.messaging.models import ChannelHealthResult
from agent33.security.auth import create_access_token

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _auth_headers(scopes: list[str] | None = None) -> dict[str, str]:
    token = create_access_token("test-user", scopes=scopes or ["admin"])
    return {"Authorization": f"Bearer {token}"}


def _clean_nats_adapters() -> None:
    """Remove the adapters dict from nats_bus if it was set during a test."""
    nats_bus = getattr(app.state, "nats_bus", None)
    if nats_bus is not None and hasattr(nats_bus, "adapters"):
        with contextlib.suppress(AttributeError):
            del nats_bus.adapters


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegisterMessagingAdapter:
    """POST /v1/connectors/messaging/register"""

    @pytest.mark.asyncio
    async def test_register_unknown_adapter_returns_400(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.post(
                "/v1/connectors/messaging/register",
                json={"adapter": "pigeon_mail", "config": {}},
            )
        assert resp.status_code == 400
        assert "pigeon_mail" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_telegram_missing_token_returns_400(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.post(
                "/v1/connectors/messaging/register",
                json={"adapter": "telegram", "config": {}},
            )
        assert resp.status_code == 400
        assert "token" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_register_adapter_start_failure_returns_unavailable(self) -> None:
        """If adapter.start() raises, the route returns status=unavailable (not 500)."""
        _target = "agent33.messaging.telegram.TelegramAdapter.start"
        with patch(_target, new_callable=AsyncMock) as mock_start:
            mock_start.side_effect = RuntimeError("network unreachable")
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_auth_headers(),
            ) as client:
                resp = await client.post(
                    "/v1/connectors/messaging/register",
                    json={"adapter": "telegram", "config": {"token": "fake-token"}},
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["adapter"] == "telegram"
        assert data["status"] == "unavailable"
        assert "network unreachable" in data["detail"]

    @pytest.mark.asyncio
    async def test_register_adapter_health_check_ok_returns_connected(self) -> None:
        """When health_check returns status='ok', the route echoes it back."""
        healthy = ChannelHealthResult(
            platform="telegram",
            status="ok",
            latency_ms=12.5,
            detail="getMe succeeded",
            queue_depth=0,
        )
        with (
            patch("agent33.messaging.telegram.TelegramAdapter.start", new_callable=AsyncMock),
            patch(
                "agent33.messaging.telegram.TelegramAdapter.health_check",
                new_callable=AsyncMock,
                return_value=healthy,
            ),
            patch("agent33.messaging.telegram.TelegramAdapter.stop", new_callable=AsyncMock),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_auth_headers(),
            ) as client:
                resp = await client.post(
                    "/v1/connectors/messaging/register",
                    json={"adapter": "telegram", "config": {"token": "valid-token"}},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["adapter"] == "telegram"
        assert data["status"] == "ok"
        assert "getMe" in data["detail"]
        _clean_nats_adapters()

    @pytest.mark.asyncio
    async def test_register_adapter_health_check_degraded_returns_degraded(self) -> None:
        degraded = ChannelHealthResult(
            platform="discord",
            status="degraded",
            detail="API returned 503",
        )
        with (
            patch("agent33.messaging.discord.DiscordAdapter.start", new_callable=AsyncMock),
            patch(
                "agent33.messaging.discord.DiscordAdapter.health_check",
                new_callable=AsyncMock,
                return_value=degraded,
            ),
            patch("agent33.messaging.discord.DiscordAdapter.stop", new_callable=AsyncMock),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                headers=_auth_headers(),
            ) as client:
                resp = await client.post(
                    "/v1/connectors/messaging/register",
                    json={"adapter": "discord", "config": {"token": "bad-token"}},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        _clean_nats_adapters()

    @pytest.mark.asyncio
    async def test_register_without_admin_scope_returns_403(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(scopes=["agents:read"]),
        ) as client:
            resp = await client.post(
                "/v1/connectors/messaging/register",
                json={"adapter": "telegram", "config": {"token": "x"}},
            )
        assert resp.status_code == 403


class TestListMessagingAdapterStatus:
    """GET /v1/connectors/messaging/status"""

    @pytest.mark.asyncio
    async def test_list_status_returns_supported_adapters(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(),
        ) as client:
            resp = await client.get("/v1/connectors/messaging/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "supported" in data
        assert "telegram" in data["supported"]
        assert "discord" in data["supported"]
        assert "adapters" in data

    @pytest.mark.asyncio
    async def test_list_status_shows_registered_adapter_after_connect(self) -> None:
        """After a successful register, the adapter appears in the status list.

        The test installs a fake nats_bus on app.state so the route can store the
        registration marker — the real lifespan does not run in unit tests.
        """

        # Install a minimal stub that supports dynamic attribute assignment.
        class _FakeBus:
            pass

        app.state.nats_bus = _FakeBus()

        healthy = ChannelHealthResult(
            platform="slack",
            status="ok",
            detail="auth.test passed",
        )
        try:
            with (
                patch("agent33.messaging.slack.SlackAdapter.start", new_callable=AsyncMock),
                patch(
                    "agent33.messaging.slack.SlackAdapter.health_check",
                    new_callable=AsyncMock,
                    return_value=healthy,
                ),
                patch("agent33.messaging.slack.SlackAdapter.stop", new_callable=AsyncMock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://test",
                    headers=_auth_headers(),
                ) as client:
                    reg_resp = await client.post(
                        "/v1/connectors/messaging/register",
                        json={"adapter": "slack", "config": {"token": "xoxb-test"}},
                    )
                    assert reg_resp.status_code == 200
                    status_resp = await client.get("/v1/connectors/messaging/status")

            assert status_resp.status_code == 200
            data = status_resp.json()
            adapter_names = [a["name"] for a in data["adapters"]]
            assert "slack" in adapter_names
        finally:
            # Restore nats_bus to None so other tests are not affected.
            app.state.nats_bus = None
            _clean_nats_adapters()

    @pytest.mark.asyncio
    async def test_list_status_without_admin_scope_returns_403(self) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=_auth_headers(scopes=["agents:read"]),
        ) as client:
            resp = await client.get("/v1/connectors/messaging/status")
        assert resp.status_code == 403
