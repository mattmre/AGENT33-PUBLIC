"""Connector boundary governance coverage for messaging adapters."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent33.messaging.discord import DiscordAdapter
from agent33.messaging.imessage import IMessageAdapter
from agent33.messaging.matrix import MatrixAdapter
from agent33.messaging.signal import SignalAdapter
from agent33.messaging.slack import SlackAdapter
from agent33.messaging.telegram import TelegramAdapter
from agent33.messaging.whatsapp import WhatsAppAdapter


class _NeverCalledClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def post(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        self.calls.append("post")
        raise AssertionError("HTTP client should not be called when governance denies")

    async def get(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        self.calls.append("get")
        raise AssertionError("HTTP client should not be called when governance denies")

    async def put(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ARG002
        self.calls.append("put")
        raise AssertionError("HTTP client should not be called when governance denies")

    async def aclose(self) -> None:
        return None


class _SuccessfulResponse:
    def __init__(self, *, status_code: int = 200, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {"ok": True, "result": []}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _adapter_factories() -> list[tuple[str, Any, str]]:
    return [
        (
            "slack",
            lambda: SlackAdapter(bot_token="xoxb-test", signing_secret="secret"),
            "C123",
        ),
        (
            "discord",
            lambda: DiscordAdapter(bot_token="token", public_key="aa" * 32),
            "123",
        ),
        ("telegram", lambda: TelegramAdapter(token="token"), "123"),
        (
            "whatsapp",
            lambda: WhatsAppAdapter(
                access_token="token",
                phone_number_id="123",
                verify_token="verify",
                app_secret="secret",
            ),
            "15550001111",
        ),
        (
            "signal",
            lambda: SignalAdapter(
                bridge_url="https://signal.example",
                sender_number="+1555",
            ),
            "+1444",
        ),
        (
            "matrix",
            lambda: MatrixAdapter(
                homeserver_url="https://matrix.example.com",
                access_token="token",
                user_id="@agent33:example.com",
            ),
            "!room:example.com",
        ),
        (
            "imessage",
            lambda: IMessageAdapter(bridge_url="https://bb.example.com"),
            "chat-guid",
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "adapter_factory", "channel_id"),
    _adapter_factories(),
)
async def test_send_governance_blocked_prevents_http_call(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    adapter_factory: Any,
    channel_id: str,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "default")
    monkeypatch.setattr(
        "agent33.config.settings.connector_governance_blocked_connectors",
        f"messaging:{platform}",
    )
    monkeypatch.setattr("agent33.config.settings.connector_governance_blocked_operations", "")

    adapter = adapter_factory()
    client = _NeverCalledClient()
    adapter._client = client

    with pytest.raises(RuntimeError) as excinfo:
        await adapter.send(channel_id, "blocked")
    assert str(excinfo.value) == (
        f"Connector governance blocked messaging:{platform}/send: "
        f"connector blocked by policy: messaging:{platform}"
    )

    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "adapter_factory", "_channel_id"),
    _adapter_factories(),
)
async def test_health_check_governance_blocked_prevents_http_call(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    adapter_factory: Any,
    _channel_id: str,  # noqa: ARG001
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "default")
    monkeypatch.setattr(
        "agent33.config.settings.connector_governance_blocked_connectors",
        f"messaging:{platform}",
    )
    monkeypatch.setattr("agent33.config.settings.connector_governance_blocked_operations", "")

    adapter = adapter_factory()
    client = _NeverCalledClient()
    adapter._client = client

    result = await adapter.health_check()

    assert result.status == "unavailable"
    assert result.detail == (
        f"Connector governance blocked messaging:{platform}/health_check: "
        f"connector blocked by policy: messaging:{platform}"
    )
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "adapter_factory", "channel_id"),
    _adapter_factories(),
)
async def test_send_boundary_invocation_preserves_connector_contract(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    adapter_factory: Any,
    channel_id: str,
) -> None:
    adapter = adapter_factory()
    adapter._client = _NeverCalledClient()
    calls: list[dict[str, Any]] = []

    async def _fake_boundary_call(**kwargs):
        calls.append(kwargs)
        return _SuccessfulResponse()

    monkeypatch.setattr(
        "agent33.messaging.discord.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.imessage.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.matrix.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.signal.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.slack.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.telegram.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.whatsapp.execute_messaging_boundary_call", _fake_boundary_call
    )

    await adapter.send(channel_id, "hello")

    assert len(calls) == 1
    assert calls[0]["connector"] == f"messaging:{platform}"
    assert calls[0]["operation"] == "send"
    assert calls[0]["payload"] == {"channel_id": channel_id}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("platform", "adapter_factory", "expected_status"),
    [
        ("slack", lambda: SlackAdapter(bot_token="xoxb-test", signing_secret="secret"), "ok"),
        ("discord", lambda: DiscordAdapter(bot_token="token", public_key="aa" * 32), "ok"),
        ("telegram", lambda: TelegramAdapter(token="token"), "degraded"),
        (
            "whatsapp",
            lambda: WhatsAppAdapter(
                access_token="token",
                phone_number_id="123",
                verify_token="verify",
                app_secret="secret",
            ),
            "ok",
        ),
        (
            "signal",
            lambda: SignalAdapter(bridge_url="https://signal.example", sender_number="+1555"),
            "degraded",
        ),
        (
            "matrix",
            lambda: MatrixAdapter(
                homeserver_url="https://matrix.example.com",
                access_token="token",
                user_id="@agent33:example.com",
            ),
            "degraded",
        ),
        ("imessage", lambda: IMessageAdapter(bridge_url="https://bb.example.com"), "degraded"),
    ],
)
async def test_health_check_boundary_invocation_preserves_connector_contract(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    adapter_factory: Any,
    expected_status: str,
) -> None:
    adapter = adapter_factory()
    adapter._client = _NeverCalledClient()
    calls: list[dict[str, Any]] = []

    async def _fake_boundary_call(**kwargs):
        calls.append(kwargs)
        return _SuccessfulResponse()

    monkeypatch.setattr(
        "agent33.messaging.discord.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.imessage.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.matrix.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.signal.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.slack.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.telegram.execute_messaging_boundary_call", _fake_boundary_call
    )
    monkeypatch.setattr(
        "agent33.messaging.whatsapp.execute_messaging_boundary_call", _fake_boundary_call
    )

    result = await adapter.health_check()

    assert result.status == expected_status
    assert len(calls) == 1
    assert calls[0]["connector"] == f"messaging:{platform}"
    assert calls[0]["operation"] == "health_check"


@pytest.mark.asyncio
async def test_telegram_poll_loop_governance_blocked_prevents_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "default")
    monkeypatch.setattr(
        "agent33.config.settings.connector_governance_blocked_connectors",
        "messaging:telegram",
    )
    monkeypatch.setattr("agent33.config.settings.connector_governance_blocked_operations", "")

    adapter = TelegramAdapter(token="token")
    client = _NeverCalledClient()
    adapter._client = client
    adapter._running = True

    async def _stop_sleep(_seconds: float) -> None:
        adapter._running = False

    monkeypatch.setattr("agent33.messaging.telegram.asyncio.sleep", _stop_sleep)

    await asyncio.wait_for(adapter._poll_loop(), timeout=1)
    assert client.calls == []


@pytest.mark.asyncio
async def test_matrix_sync_loop_governance_blocked_prevents_http_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("agent33.config.settings.connector_boundary_enabled", True)
    monkeypatch.setattr("agent33.config.settings.connector_policy_pack", "default")
    monkeypatch.setattr(
        "agent33.config.settings.connector_governance_blocked_connectors",
        "messaging:matrix",
    )
    monkeypatch.setattr("agent33.config.settings.connector_governance_blocked_operations", "")

    adapter = MatrixAdapter(
        homeserver_url="https://matrix.example.com",
        access_token="token",
        user_id="@agent33:example.com",
    )
    client = _NeverCalledClient()
    adapter._client = client
    adapter._running = True

    async def _stop_sleep(_seconds: float) -> None:
        adapter._running = False

    monkeypatch.setattr("agent33.messaging.matrix.asyncio.sleep", _stop_sleep)

    await asyncio.wait_for(adapter._sync_loop(), timeout=1)
    assert client.calls == []


@pytest.mark.asyncio
async def test_telegram_poll_loop_boundary_operation_name_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = TelegramAdapter(token="token")
    adapter._client = _NeverCalledClient()
    adapter._running = True
    calls: list[dict[str, Any]] = []

    async def _fake_boundary_call(**kwargs):
        calls.append(kwargs)
        adapter._running = False
        return _SuccessfulResponse(payload={"ok": True, "result": []})

    monkeypatch.setattr(
        "agent33.messaging.telegram.execute_messaging_boundary_call", _fake_boundary_call
    )

    await asyncio.wait_for(adapter._poll_loop(), timeout=1)

    assert len(calls) == 1
    assert calls[0]["connector"] == "messaging:telegram"
    assert calls[0]["operation"] == "poll_updates"


@pytest.mark.asyncio
async def test_matrix_sync_loop_boundary_operation_name_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = MatrixAdapter(
        homeserver_url="https://matrix.example.com",
        access_token="token",
        user_id="@agent33:example.com",
    )
    adapter._client = _NeverCalledClient()
    adapter._running = True
    calls: list[dict[str, Any]] = []

    async def _fake_boundary_call(**kwargs):
        calls.append(kwargs)
        adapter._running = False
        return _SuccessfulResponse(payload={"next_batch": "batch", "rooms": {"join": {}}})

    monkeypatch.setattr(
        "agent33.messaging.matrix.execute_messaging_boundary_call", _fake_boundary_call
    )

    await asyncio.wait_for(adapter._sync_loop(), timeout=1)

    assert len(calls) == 1
    assert calls[0]["connector"] == "messaging:matrix"
    assert calls[0]["operation"] == "sync_loop"
