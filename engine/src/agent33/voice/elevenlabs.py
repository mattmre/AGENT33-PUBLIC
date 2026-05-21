"""ElevenLabs audio transport for the voice sidecar.

Provides HTTP-based TTS synthesis, streaming WebSocket TTS, voice listing,
and audio artifact persistence for ElevenLabs integration.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

_ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
_ELEVENLABS_WS_BASE = "wss://api.elevenlabs.io"


@dataclass
class ElevenLabsConfig:
    """Configuration for the ElevenLabs audio transport."""

    api_key: str = ""
    model_id: str = "eleven_multilingual_v2"
    voice_id: str = ""
    stability: float = 0.5
    similarity_boost: float = 0.75
    output_format: str = "mp3_44100_128"
    optimize_streaming_latency: int = 3
    websocket_url: str = "wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"

    def __post_init__(self) -> None:
        if not 0.0 <= self.stability <= 1.0:
            raise ValueError("stability must be between 0.0 and 1.0")
        if not 0.0 <= self.similarity_boost <= 1.0:
            raise ValueError("similarity_boost must be between 0.0 and 1.0")
        if self.optimize_streaming_latency < 0 or self.optimize_streaming_latency > 4:
            raise ValueError("optimize_streaming_latency must be between 0 and 4")

    def resolved_websocket_url(self) -> str:
        """Return the WebSocket URL with the voice_id interpolated."""
        return self.websocket_url.format(voice_id=self.voice_id)


class ElevenLabsTransportError(Exception):
    """Raised when the ElevenLabs API returns an error or is unreachable."""

    def __init__(self, message: str, status_code: int = 0, detail: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class ElevenLabsTransport:
    """HTTP and WebSocket transport for ElevenLabs TTS API.

    All HTTP calls use ``httpx.AsyncClient``. The transport does not hold
    long-lived connections; each method creates a short-lived client scoped
    to the request.
    """

    def __init__(self, config: ElevenLabsConfig) -> None:
        self._config = config

    @property
    def config(self) -> ElevenLabsConfig:
        return self._config

    def _headers(self) -> dict[str, str]:
        """Build authorization headers for the ElevenLabs API."""
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._config.api_key:
            headers["xi-api-key"] = self._config.api_key
        return headers

    def _tts_url(self, voice_id: str | None = None) -> str:
        """Build the TTS endpoint URL."""
        vid = voice_id or self._config.voice_id
        return f"{_ELEVENLABS_API_BASE}/v1/text-to-speech/{vid}"

    async def synthesize(self, text: str, *, voice_id: str | None = None) -> bytes:
        """Synthesize *text* to audio bytes via the HTTP TTS endpoint.

        Returns raw audio bytes in the configured ``output_format``.
        Raises ``ElevenLabsTransportError`` on API or network errors.
        """
        if not text:
            raise ValueError("text must not be empty")

        vid = voice_id or self._config.voice_id
        if not vid:
            raise ValueError("voice_id must be set in config or passed explicitly")

        url = self._tts_url(vid)
        body: dict[str, Any] = {
            "text": text,
            "model_id": self._config.model_id,
            "voice_settings": {
                "stability": self._config.stability,
                "similarity_boost": self._config.similarity_boost,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json=body,
                    headers={
                        **self._headers(),
                        "Accept": "audio/mpeg",
                    },
                    params={"output_format": self._config.output_format},
                )
                if response.status_code != 200:
                    detail = ""
                    try:
                        error_body = response.json()
                        detail = str(error_body.get("detail", error_body))
                    except Exception:
                        detail = response.text
                    raise ElevenLabsTransportError(
                        f"ElevenLabs TTS failed with status {response.status_code}",
                        status_code=response.status_code,
                        detail=detail,
                    )
                return response.content
        except ElevenLabsTransportError:
            raise
        except httpx.HTTPError as exc:
            raise ElevenLabsTransportError(
                f"Network error calling ElevenLabs TTS: {exc}",
                detail=str(exc),
            ) from exc

    async def synthesize_stream(
        self, text: str, *, voice_id: str | None = None
    ) -> AsyncIterator[bytes]:
        """Stream TTS audio chunks via the ElevenLabs WebSocket API.

        Yields audio byte chunks as they arrive from the streaming endpoint.
        This uses the HTTP streaming endpoint (chunked transfer) rather than
        a true WebSocket, which keeps the implementation simpler and avoids
        adding a WebSocket client dependency.

        Raises ``ElevenLabsTransportError`` on API or network errors.
        """
        if not text:
            raise ValueError("text must not be empty")

        vid = voice_id or self._config.voice_id
        if not vid:
            raise ValueError("voice_id must be set in config or passed explicitly")

        url = f"{self._tts_url(vid)}/stream"
        body: dict[str, Any] = {
            "text": text,
            "model_id": self._config.model_id,
            "voice_settings": {
                "stability": self._config.stability,
                "similarity_boost": self._config.similarity_boost,
            },
        }

        try:
            async with (
                httpx.AsyncClient(timeout=60.0) as client,
                client.stream(
                    "POST",
                    url,
                    json=body,
                    headers={
                        **self._headers(),
                        "Accept": "audio/mpeg",
                    },
                    params={
                        "output_format": self._config.output_format,
                        "optimize_streaming_latency": str(self._config.optimize_streaming_latency),
                    },
                ) as response,
            ):
                if response.status_code != 200:
                    body_text = await response.aread()
                    detail = body_text.decode("utf-8", errors="replace")
                    raise ElevenLabsTransportError(
                        f"ElevenLabs streaming TTS failed with status {response.status_code}",
                        status_code=response.status_code,
                        detail=detail,
                    )
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    yield chunk
        except ElevenLabsTransportError:
            raise
        except httpx.HTTPError as exc:
            raise ElevenLabsTransportError(
                f"Network error during ElevenLabs streaming TTS: {exc}",
                detail=str(exc),
            ) from exc

    async def list_voices(self) -> list[dict[str, Any]]:
        """Fetch available voices from the ElevenLabs API.

        Returns a list of voice dictionaries as provided by the API.
        Raises ``ElevenLabsTransportError`` on API or network errors.
        """
        url = f"{_ELEVENLABS_API_BASE}/v1/voices"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=self._headers())
                if response.status_code != 200:
                    raise ElevenLabsTransportError(
                        f"ElevenLabs list_voices failed with status {response.status_code}",
                        status_code=response.status_code,
                        detail=response.text,
                    )
                payload = response.json()
                voices: list[dict[str, Any]] = payload.get("voices", [])
                return voices
        except ElevenLabsTransportError:
            raise
        except httpx.HTTPError as exc:
            raise ElevenLabsTransportError(
                f"Network error listing ElevenLabs voices: {exc}",
                detail=str(exc),
            ) from exc

    async def get_voice(self, voice_id: str) -> dict[str, Any]:
        """Fetch details for a single voice from the ElevenLabs API.

        Raises ``ElevenLabsTransportError`` on API or network errors.
        """
        url = f"{_ELEVENLABS_API_BASE}/v1/voices/{voice_id}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=self._headers())
                if response.status_code != 200:
                    raise ElevenLabsTransportError(
                        f"ElevenLabs get_voice failed with status {response.status_code}",
                        status_code=response.status_code,
                        detail=response.text,
                    )
                result: dict[str, Any] = response.json()
                return result
        except ElevenLabsTransportError:
            raise
        except httpx.HTTPError as exc:
            raise ElevenLabsTransportError(
                f"Network error fetching ElevenLabs voice {voice_id}: {exc}",
                detail=str(exc),
            ) from exc

    async def health_check(self) -> bool:
        """Verify API key validity and connectivity.

        Returns ``True`` if the API responds successfully, ``False`` otherwise.
        """
        if not self._config.api_key:
            return False
        try:
            voices = await self.list_voices()
            return isinstance(voices, list)
        except ElevenLabsTransportError:
            return False
        except Exception:
            return False


@dataclass
class _ArtifactMetadata:
    """Internal metadata for a saved audio artifact."""

    artifact_id: str
    session_id: str
    text: str
    audio_format: str
    file_path: str
    size_bytes: int
    created_at: str


@dataclass
class ElevenLabsArtifactStore:
    """Persist and retrieve synthesized audio artifacts on the local filesystem.

    Each session gets a subdirectory under ``storage_dir``. Audio files are
    stored with a UUID-based filename alongside a JSON manifest tracking
    metadata.
    """

    storage_dir: Path
    _manifests: dict[str, list[_ArtifactMetadata]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save_audio(
        self,
        session_id: str,
        text: str,
        audio_data: bytes,
        audio_format: str = "mp3",
    ) -> str:
        """Save an audio artifact for *session_id* and return its file path.

        The artifact is persisted to disk and tracked in the in-memory manifest.
        """
        session_dir = self.storage_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        artifact_id = uuid4().hex
        filename = f"{artifact_id}.{audio_format}"
        file_path = session_dir / filename
        file_path.write_bytes(audio_data)

        meta = _ArtifactMetadata(
            artifact_id=artifact_id,
            session_id=session_id,
            text=text,
            audio_format=audio_format,
            file_path=str(file_path),
            size_bytes=len(audio_data),
            created_at=datetime.now(UTC).isoformat(),
        )
        self._manifests.setdefault(session_id, []).append(meta)

        # Persist manifest to disk so it survives restarts
        self._write_manifest(session_id)

        logger.debug(
            "elevenlabs.artifact_saved",
            extra={
                "artifact_id": artifact_id,
                "session_id": session_id,
                "size_bytes": len(audio_data),
            },
        )
        return str(file_path)

    def list_artifacts(self, session_id: str) -> list[dict[str, Any]]:
        """List all audio artifacts for *session_id*.

        Returns a list of metadata dictionaries. Loads from disk if not
        already in memory.
        """
        if session_id not in self._manifests:
            self._load_manifest(session_id)
        artifacts = self._manifests.get(session_id, [])
        return [
            {
                "artifact_id": a.artifact_id,
                "session_id": a.session_id,
                "text": a.text,
                "audio_format": a.audio_format,
                "file_path": a.file_path,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at,
            }
            for a in artifacts
        ]

    def get_artifact(self, artifact_id: str) -> Path | None:
        """Return the file path for *artifact_id*, or ``None`` if not found.

        Searches all loaded sessions and the filesystem.
        """
        # Search in-memory manifests first
        for artifacts in self._manifests.values():
            for a in artifacts:
                if a.artifact_id == artifact_id:
                    path = Path(a.file_path)
                    return path if path.exists() else None

        # Fall back to filesystem scan
        if not self.storage_dir.exists():
            return None
        for session_dir in self.storage_dir.iterdir():
            if not session_dir.is_dir():
                continue
            for file in session_dir.iterdir():
                if file.stem == artifact_id and file.is_file():
                    return file
        return None

    def _write_manifest(self, session_id: str) -> None:
        """Write the in-memory manifest for *session_id* to disk."""
        session_dir = self.storage_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = session_dir / "manifest.json"
        artifacts = self._manifests.get(session_id, [])
        data = [
            {
                "artifact_id": a.artifact_id,
                "session_id": a.session_id,
                "text": a.text,
                "audio_format": a.audio_format,
                "file_path": a.file_path,
                "size_bytes": a.size_bytes,
                "created_at": a.created_at,
            }
            for a in artifacts
        ]
        manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_manifest(self, session_id: str) -> None:
        """Load a session manifest from disk into memory."""
        manifest_path = self.storage_dir / session_id / "manifest.json"
        if not manifest_path.exists():
            self._manifests[session_id] = []
            return
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._manifests[session_id] = []
            return
        artifacts: list[_ArtifactMetadata] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                artifacts.append(
                    _ArtifactMetadata(
                        artifact_id=item["artifact_id"],
                        session_id=item["session_id"],
                        text=item["text"],
                        audio_format=item["audio_format"],
                        file_path=item["file_path"],
                        size_bytes=item["size_bytes"],
                        created_at=item["created_at"],
                    )
                )
            except (KeyError, TypeError):
                continue
        self._manifests[session_id] = artifacts
