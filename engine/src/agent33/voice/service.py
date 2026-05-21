"""Service implementation for the standalone voice sidecar."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from agent33.voice.models import (
    AudioFormatConfig,
    VoicePersona,
    VoiceSidecarHealth,
    VoiceSidecarSession,
    VoiceSidecarSessionState,
)
from agent33.voice.providers import (
    AudioFormat,
    STTProvider,
    STTResult,
    StubSTTProvider,
    StubTTSProvider,
    TTSProvider,
    TTSResult,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_PERSONA = VoicePersona(
    id="default",
    name="AGENT-33 Default",
    provider="stub",
    voice_id="agent33-default",
    style="balanced",
    description="Default local fallback voice persona for the standalone sidecar.",
)


class VoiceSidecarService:
    """Own voice-sidecar session state, persona config, and artifact persistence.

    Phase 35: now delegates TTS/STT to pluggable providers via the
    ``TTSProvider`` and ``STTProvider`` protocols.
    """

    def __init__(
        self,
        *,
        voices_path: Path,
        artifacts_dir: Path,
        playback_backend: str = "noop",
        tts_provider: TTSProvider | None = None,
        stt_provider: STTProvider | None = None,
    ) -> None:
        self._voices_path = voices_path
        self._artifacts_dir = artifacts_dir
        self._playback_backend = playback_backend
        self._tts_provider: TTSProvider = tts_provider or StubTTSProvider()
        self._stt_provider: STTProvider = stt_provider or StubSTTProvider()
        self._sessions: dict[str, VoiceSidecarSession] = {}
        self._personas = self._load_personas()
        self._shutting_down = False

    @property
    def voices_path(self) -> Path:
        return self._voices_path

    @property
    def artifacts_dir(self) -> Path:
        return self._artifacts_dir

    @property
    def tts_provider(self) -> TTSProvider:
        return self._tts_provider

    @property
    def stt_provider(self) -> STTProvider:
        return self._stt_provider

    def list_personas(self) -> list[VoicePersona]:
        """Return configured personas."""
        return list(self._personas.values())

    def start_session(
        self,
        *,
        room_name: str,
        requested_by: str = "",
        metadata: dict[str, Any] | None = None,
        persona_id: str = "default",
        audio_format: AudioFormatConfig | None = None,
        agent_session_id: str = "",
    ) -> VoiceSidecarSession:
        """Create and persist a new voice sidecar session."""
        resolved_persona = self._resolve_persona(persona_id)
        session_id = uuid4().hex
        artifacts_path = self._artifacts_dir / session_id
        artifacts_path.mkdir(parents=True, exist_ok=True)
        session = VoiceSidecarSession(
            session_id=session_id,
            room_name=room_name,
            requested_by=requested_by,
            persona_id=resolved_persona.id,
            metadata=metadata or {},
            artifacts_path=str((artifacts_path / "events.jsonl").resolve()),
            audio_format=audio_format or AudioFormatConfig(),
            agent_session_id=agent_session_id,
            tts_provider=self._tts_provider.provider_name,
            stt_provider=self._stt_provider.provider_name,
        )
        self._sessions[session_id] = session
        self._write_manifest(session)
        self._append_event(
            session,
            {
                "type": "session.started",
                "requested_by": requested_by,
                "persona_id": resolved_persona.id,
                "audio_format": (audio_format or AudioFormatConfig()).model_dump(),
                "agent_session_id": agent_session_id,
            },
        )
        return session

    def list_sessions(self) -> list[VoiceSidecarSession]:
        """Return all sessions, newest first."""
        return sorted(
            self._sessions.values(),
            key=lambda session: session.created_at,
            reverse=True,
        )

    def get_session(self, session_id: str) -> VoiceSidecarSession | None:
        """Fetch a session by ID."""
        return self._sessions.get(session_id)

    def stop_session(self, session_id: str) -> VoiceSidecarSession:
        """Stop a running session."""
        session = self._require_session(session_id)
        if session.state == VoiceSidecarSessionState.STOPPED:
            return session
        session.state = VoiceSidecarSessionState.STOPPED
        session.stopped_at = datetime.now(UTC)
        self._write_manifest(session)
        self._append_event(session, {"type": "session.stopped"})
        return session

    def delete_session(self, session_id: str) -> bool:
        """Delete a session entirely (stop if active, then remove).

        Returns True if the session existed and was deleted.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.state == VoiceSidecarSessionState.ACTIVE:
            self.stop_session(session_id)
        del self._sessions[session_id]
        return True

    async def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        session_id: str = "",
    ) -> TTSResult:
        """Synthesize text via the configured TTS provider.

        If *session_id* is provided, the synthesis event is logged against
        the session.
        """
        result = await self._tts_provider.synthesize(text, voice_id=voice_id)
        if session_id:
            session = self._sessions.get(session_id)
            if session is not None:
                self._append_event(
                    session,
                    {
                        "type": "tts.synthesized",
                        "text_length": len(text),
                        "audio_bytes": len(result.audio_data),
                        "provider": result.provider,
                    },
                )
        return result

    async def transcribe(
        self,
        audio_data: bytes,
        *,
        language: str = "",
        session_id: str = "",
    ) -> STTResult:
        """Transcribe audio via the configured STT provider.

        If *session_id* is provided, the transcription event is logged
        against the session.
        """
        result = await self._stt_provider.transcribe(audio_data, language=language)
        if session_id:
            session = self._sessions.get(session_id)
            if session is not None:
                self._append_event(
                    session,
                    {
                        "type": "stt.transcribed",
                        "audio_bytes": len(audio_data),
                        "text_length": len(result.text),
                        "provider": result.provider,
                    },
                )
        return result

    async def handle_websocket(self, session_id: str, websocket: WebSocket) -> None:
        """Accept websocket traffic for a sidecar session and persist the event stream."""
        session = self._require_session(session_id)
        await websocket.accept()
        session.websocket_connections += 1
        self._write_manifest(session)
        self._append_event(session, {"type": "ws.connected"})
        try:
            while True:
                payload = await websocket.receive_text()
                self._append_event(session, {"type": "ws.message", "payload": payload})
                await websocket.send_json(
                    {
                        "type": "ack",
                        "session_id": session.session_id,
                        "received_at": datetime.now(UTC).isoformat(),
                    }
                )
        except WebSocketDisconnect:
            self._append_event(session, {"type": "ws.disconnected"})
        finally:
            session.websocket_connections = max(0, session.websocket_connections - 1)
            self._write_manifest(session)

    async def shutdown(self) -> None:
        """Mark the service as shutting down and stop all active sessions."""
        self._shutting_down = True
        for session in list(self._sessions.values()):
            if session.state == VoiceSidecarSessionState.ACTIVE:
                self.stop_session(session.session_id)

    def health_snapshot(self) -> VoiceSidecarHealth:
        """Build a deterministic health snapshot."""
        session_count = len(self._sessions)
        active_sessions = sum(
            1
            for session in self._sessions.values()
            if session.state == VoiceSidecarSessionState.ACTIVE
        )
        websocket_connections = sum(
            session.websocket_connections for session in self._sessions.values()
        )
        return VoiceSidecarHealth(
            status="healthy" if not self._shutting_down else "degraded",
            playback_backend=self._playback_backend,
            voices_path=str(self._voices_path),
            artifacts_dir=str(self._artifacts_dir),
            persona_count=len(self._personas),
            session_count=session_count,
            active_sessions=active_sessions,
            websocket_connections=websocket_connections,
            tts_provider=self._tts_provider.provider_name,
            stt_provider=self._stt_provider.provider_name,
            shutting_down=self._shutting_down,
        )

    # ------------------------------------------------------------------
    # Provider resolution helper
    # ------------------------------------------------------------------

    def _audio_format_from_config(self, config: AudioFormatConfig) -> AudioFormat:
        """Convert a Pydantic AudioFormatConfig to a provider AudioFormat."""
        from agent33.voice.providers import AudioEncoding

        try:
            encoding = AudioEncoding(config.encoding)
        except ValueError:
            encoding = AudioEncoding.PCM_S16LE
        return AudioFormat(
            encoding=encoding,
            sample_rate=config.sample_rate,
            channels=config.channels,
            bit_depth=config.bit_depth,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_personas(self) -> dict[str, VoicePersona]:
        """Load personas from ``voices.json`` with a safe default fallback."""
        if not self._voices_path.exists():
            return {_DEFAULT_PERSONA.id: _DEFAULT_PERSONA}
        try:
            payload = json.loads(self._voices_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {_DEFAULT_PERSONA.id: _DEFAULT_PERSONA}

        raw_personas = payload.get("voices", payload) if isinstance(payload, dict) else payload
        if not isinstance(raw_personas, list):
            return {_DEFAULT_PERSONA.id: _DEFAULT_PERSONA}

        personas: dict[str, VoicePersona] = {}
        for item in raw_personas:
            if not isinstance(item, dict):
                continue
            try:
                persona = VoicePersona.model_validate(item)
            except Exception:
                continue
            personas[persona.id] = persona
        if not personas:
            personas[_DEFAULT_PERSONA.id] = _DEFAULT_PERSONA
        return personas

    def _resolve_persona(self, persona_id: str) -> VoicePersona:
        """Return a configured persona, falling back to the default."""
        if persona_id in self._personas:
            return self._personas[persona_id]
        return self._personas.get("default", _DEFAULT_PERSONA)

    def _require_session(self, session_id: str) -> VoiceSidecarSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(f"Voice sidecar session '{session_id}' not found")
        return session

    def _write_manifest(self, session: VoiceSidecarSession) -> None:
        session_dir = self._artifacts_dir / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.json").write_text(
            json.dumps(session.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )

    def _append_event(self, session: VoiceSidecarSession, payload: dict[str, Any]) -> None:
        session_dir = self._artifacts_dir / session.session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }
        with (session_dir / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")
