"""Client and compatibility shim for talking to the standalone voice sidecar."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx


class VoiceSidecarClient:
    """Thin async client for the standalone voice sidecar."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def health(self) -> dict[str, Any]:
        """Return the sidecar health payload or an availability error snapshot."""
        if not self._base_url:
            return {
                "status": "unconfigured",
                "detail": "voice sidecar URL is not configured",
            }
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                transport=self._transport,
            ) as client:
                response = await client.get("/health")
                response.raise_for_status()
        except Exception as exc:
            return {
                "status": "unavailable",
                "detail": str(exc),
            }
        payload = response.json()
        status = payload.get("status", "degraded")
        normalized = "ok" if status == "healthy" else status
        snapshot = dict(payload)
        snapshot["status"] = normalized
        return snapshot

    async def start_session(
        self,
        *,
        room_name: str,
        requested_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a session in the sidecar."""
        if not self._base_url:
            raise RuntimeError("voice sidecar URL is not configured")
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.post(
                "/v1/voice/sessions",
                json={
                    "room_name": room_name,
                    "requested_by": requested_by,
                    "metadata": metadata or {},
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("voice sidecar returned a non-object session payload")
            return dict(payload)

    async def stop_session(self, session_id: str) -> dict[str, Any]:
        """Stop a sidecar session."""
        if not self._base_url:
            raise RuntimeError("voice sidecar URL is not configured")
        async with httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            transport=self._transport,
        ) as client:
            response = await client.post(f"/v1/voice/sessions/{session_id}/stop")
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise RuntimeError("voice sidecar returned a non-object session payload")
            return dict(payload)


class VoiceSidecarProbe:
    """Probe object exposed on ``app.state`` for health/status aggregation."""

    def __init__(
        self,
        *,
        base_url: str,
        enabled: bool,
        transport: str,
        timeout_seconds: float = 2.0,
        client: VoiceSidecarClient | None = None,
    ) -> None:
        self._enabled = enabled
        self._transport = transport
        self._client = client or VoiceSidecarClient(base_url, timeout_seconds=timeout_seconds)

    async def health_snapshot(self) -> dict[str, Any]:
        """Return a normalized sidecar health snapshot for operator surfaces."""
        if not self._enabled:
            return {"status": "unconfigured", "detail": "voice runtime is disabled"}
        if self._transport != "sidecar":
            return {
                "status": "configured",
                "detail": f"voice transport is '{self._transport}', not 'sidecar'",
            }
        return await self._client.health()


class SidecarVoiceDaemon:
    """Compatibility shim that backs multimodal sessions with the standalone sidecar."""

    def __init__(
        self,
        room_name: str,
        url: str,
        api_key: str,
        api_secret: str,
        *,
        transport: str = "sidecar",
        client: VoiceSidecarClient | None = None,
    ) -> None:
        self._room_name = room_name
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._transport = transport
        self._client = client or VoiceSidecarClient(url)
        self._active = False
        self._started_at: datetime | None = None
        self._stopped_at: datetime | None = None
        self._sidecar_session_id = ""
        self._last_health: dict[str, Any] = {"status": "unconfigured"}

    async def start(self) -> None:
        """Start the remote sidecar session."""
        if self._transport != "sidecar":
            raise ValueError(f"Unsupported voice daemon transport: {self._transport}")
        payload = await self._client.start_session(
            room_name=self._room_name,
            metadata={
                "api_key_present": bool(self._api_key),
                "api_secret_present": bool(self._api_secret),
            },
        )
        self._sidecar_session_id = str(payload.get("session_id", ""))
        self._active = True
        self._started_at = datetime.now(UTC)
        self._stopped_at = None
        self._last_health = await self._client.health()

    async def stop(self) -> None:
        """Stop the remote sidecar session."""
        if not self._active:
            return
        if self._sidecar_session_id:
            await self._client.stop_session(self._sidecar_session_id)
        self._active = False
        self._stopped_at = datetime.now(UTC)
        self._last_health = await self._client.health()

    def health_check(self) -> bool:
        """Return the last known sidecar health state."""
        return self._active and self._last_health.get("status") == "ok"

    async def process_audio_chunk(self, chunk: bytes) -> str | None:
        """Realtime media transport lives inside the sidecar websocket layer."""
        if not self._active:
            raise RuntimeError("Voice daemon is not active")
        return None

    async def synthesize_speech(self, text: str) -> bytes | None:
        """Realtime synthesis is delegated to the sidecar runtime."""
        if not self._active:
            raise RuntimeError("Voice daemon is not active")
        return None

    def snapshot(self) -> dict[str, object]:
        """Return deterministic sidecar-backed daemon state."""
        return {
            "room_name": self._room_name,
            "transport": self._transport,
            "active": self._active,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "stopped_at": self._stopped_at.isoformat() if self._stopped_at else None,
            "sidecar_session_id": self._sidecar_session_id,
            "sidecar_url": self._url,
            "health": self._last_health,
        }
