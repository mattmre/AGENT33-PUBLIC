"""Tests for the standalone voice sidecar package and client shim."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi.testclient import TestClient

from agent33.voice.app import create_voice_sidecar_app
from agent33.voice.client import SidecarVoiceDaemon, VoiceSidecarClient, VoiceSidecarProbe
from agent33.voice.service import VoiceSidecarService

if TYPE_CHECKING:
    from pathlib import Path


def _make_service(tmp_path: Path) -> VoiceSidecarService:
    voices_path = tmp_path / "voices.json"
    voices_path.write_text(
        json.dumps({"voices": [{"id": "default", "name": "Default"}]}),
        encoding="utf-8",
    )
    return VoiceSidecarService(
        voices_path=voices_path,
        artifacts_dir=tmp_path / "artifacts",
        playback_backend="noop",
    )


@pytest.mark.asyncio
async def test_sidecar_health_and_session_lifecycle(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    app = create_voice_sidecar_app(service)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/health")
        assert health.status_code == 200
        assert health.json()["status"] == "healthy"

        created = await client.post(
            "/v1/voice/sessions",
            json={"room_name": "agent33-room", "requested_by": "pytest"},
        )
        assert created.status_code == 201
        payload = created.json()
        assert payload["room_name"] == "agent33-room"
        assert payload["state"] == "active"

        listing = await client.get("/v1/voice/sessions")
        assert listing.status_code == 200
        assert len(listing.json()) == 1

        stopped = await client.post(f"/v1/voice/sessions/{payload['session_id']}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["state"] == "stopped"


def test_sidecar_websocket_records_messages(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    app = create_voice_sidecar_app(service)
    session = service.start_session(room_name="ws-room", requested_by="pytest")

    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws/voice/{session.session_id}") as websocket,
    ):
        websocket.send_text("hello")
        reply = websocket.receive_json()
        assert reply["type"] == "ack"
        assert reply["session_id"] == session.session_id

    events_file = tmp_path / "artifacts" / session.session_id / "events.jsonl"
    contents = events_file.read_text(encoding="utf-8")
    assert "ws.message" in contents
    assert "hello" in contents


@pytest.mark.asyncio
async def test_sidecar_client_and_probe_normalize_health(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    app = create_voice_sidecar_app(service)
    transport = httpx.ASGITransport(app=app)
    client = VoiceSidecarClient(
        "http://testserver",
        transport=transport,
    )

    health = await client.health()
    assert health["status"] == "ok"

    probe = VoiceSidecarProbe(
        base_url="http://testserver",
        enabled=True,
        transport="sidecar",
        client=client,
    )
    snapshot = await probe.health_snapshot()
    assert snapshot["status"] == "ok"


@pytest.mark.asyncio
async def test_sidecar_voice_daemon_uses_client(tmp_path: Path) -> None:
    service = _make_service(tmp_path)
    app = create_voice_sidecar_app(service)
    transport = httpx.ASGITransport(app=app)
    client = VoiceSidecarClient(
        "http://testserver",
        transport=transport,
    )
    daemon = SidecarVoiceDaemon(
        room_name="daemon-room",
        url="http://testserver",
        api_key="",
        api_secret="",
        client=client,
    )

    await daemon.start()
    assert daemon.health_check() is True
    snapshot = daemon.snapshot()
    assert snapshot["sidecar_session_id"]

    await daemon.stop()
    assert daemon.health_check() is False
