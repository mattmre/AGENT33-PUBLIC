"""FastAPI app factory for the standalone voice sidecar."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Form, HTTPException, UploadFile, WebSocket
from pydantic import BaseModel, Field

from agent33.voice.elevenlabs import (
    ElevenLabsArtifactStore,
    ElevenLabsConfig,
    ElevenLabsTransport,
    ElevenLabsTransportError,
)
from agent33.voice.livekit_transport import (
    LiveKitConfig,
    LiveKitTransport,
    LiveKitTransportError,
)
from agent33.voice.models import AudioFormatConfig  # noqa: TC001 (Pydantic runtime)
from agent33.voice.service import VoiceSidecarService

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from agent33.voice.providers import STTProvider, TTSProvider

logger = logging.getLogger(__name__)


class StartVoiceSidecarSessionRequest(BaseModel):
    """Request body for starting a sidecar session."""

    room_name: str
    requested_by: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    persona_id: str = "default"
    audio_format: AudioFormatConfig | None = None
    agent_session_id: str = ""


class SynthesizeRequest(BaseModel):
    """Request body for text-to-speech synthesis."""

    text: str
    voice_id: str = ""
    session_id: str = ""


class TranscribeRequest(BaseModel):
    """Request body for speech-to-text transcription (JSON mode).

    For binary audio upload, use the multipart ``/v1/voice/transcribe``
    endpoint with a file field.
    """

    audio_base64: str = ""
    language: str = ""
    session_id: str = ""


class CreateLiveKitRoomRequest(BaseModel):
    """Request body for creating a LiveKit room."""

    name: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerateLiveKitTokenRequest(BaseModel):
    """Request body for generating a LiveKit access token."""

    room_name: str
    identity: str
    ttl: int | None = None


def create_voice_sidecar_app(
    service: VoiceSidecarService | None = None,
    *,
    elevenlabs_config: ElevenLabsConfig | None = None,
    elevenlabs_artifact_store: ElevenLabsArtifactStore | None = None,
    livekit_config: LiveKitConfig | None = None,
    tts_provider: TTSProvider | None = None,
    stt_provider: STTProvider | None = None,
) -> FastAPI:
    """Create a standalone FastAPI voice sidecar app."""
    resolved_service = service or VoiceSidecarService(
        voices_path=Path("config/voice/voices.json"),
        artifacts_dir=Path("var/voice-sidecar"),
        playback_backend="noop",
        tts_provider=tts_provider,
        stt_provider=stt_provider,
    )

    el_config = elevenlabs_config or ElevenLabsConfig()
    el_transport = ElevenLabsTransport(el_config) if el_config.api_key else None
    el_store = elevenlabs_artifact_store or ElevenLabsArtifactStore(
        storage_dir=resolved_service.artifacts_dir / "elevenlabs",
    )

    lk_config = livekit_config or LiveKitConfig()
    lk_transport = LiveKitTransport(lk_config) if lk_config.is_configured else None

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
        yield
        await resolved_service.shutdown()

    app = FastAPI(title="AGENT-33 Voice Sidecar", version="0.2.0", lifespan=_lifespan)
    app.state.voice_sidecar_service = resolved_service
    app.state.elevenlabs_transport = el_transport
    app.state.elevenlabs_artifact_store = el_store
    app.state.livekit_transport = lk_transport
    app.state.livekit_config = lk_config

    # ------------------------------------------------------------------
    # Core sidecar endpoints
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return resolved_service.health_snapshot().model_dump(mode="json")

    @app.get("/v1/voice/personas")
    async def list_personas() -> list[dict[str, Any]]:
        return [persona.model_dump(mode="json") for persona in resolved_service.list_personas()]

    @app.get("/v1/voice/sessions")
    async def list_sessions() -> list[dict[str, Any]]:
        return [session.model_dump(mode="json") for session in resolved_service.list_sessions()]

    @app.post("/v1/voice/sessions", status_code=201)
    async def start_session(body: StartVoiceSidecarSessionRequest) -> dict[str, Any]:
        session = resolved_service.start_session(
            room_name=body.room_name,
            requested_by=body.requested_by,
            metadata=body.metadata,
            persona_id=body.persona_id,
            audio_format=body.audio_format,
            agent_session_id=body.agent_session_id,
        )
        return session.model_dump(mode="json")

    @app.get("/v1/voice/sessions/{session_id}")
    async def get_session(session_id: str) -> dict[str, Any]:
        session = resolved_service.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Voice sidecar session not found")
        return session.model_dump(mode="json")

    @app.post("/v1/voice/sessions/{session_id}/stop")
    async def stop_session(session_id: str) -> dict[str, Any]:
        try:
            session = resolved_service.stop_session(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return session.model_dump(mode="json")

    @app.delete("/v1/voice/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, Any]:
        deleted = resolved_service.delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Voice sidecar session not found")
        return {"status": "deleted", "session_id": session_id}

    @app.websocket("/ws/voice/{session_id}")
    async def voice_stream(websocket: WebSocket, session_id: str) -> None:
        try:
            await resolved_service.handle_websocket(session_id, websocket)
        except KeyError:
            await websocket.close(code=1008, reason="voice session not found")

    # ------------------------------------------------------------------
    # Provider-agnostic TTS endpoint (Phase 35)
    # ------------------------------------------------------------------

    @app.post("/v1/voice/synthesize")
    async def synthesize(body: SynthesizeRequest) -> dict[str, Any]:
        """Synthesize text to audio using the configured TTS provider.

        Falls back to the ElevenLabs direct transport for backward
        compatibility when the provider-agnostic layer returns stub results
        and an ElevenLabs transport is configured.
        """
        if not body.text:
            raise HTTPException(status_code=400, detail="text must not be empty")

        # Try provider-agnostic path first
        try:
            result = await resolved_service.synthesize(
                body.text,
                voice_id=body.voice_id,
                session_id=body.session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        # If the TTS provider is non-stub, use its result directly
        if result.provider != "stub":
            file_path = ""
            if body.session_id:
                file_path = el_store.save_audio(
                    session_id=body.session_id,
                    text=body.text,
                    audio_data=result.audio_data,
                    audio_format=result.audio_format.encoding.value.split("_")[0],
                )
            return {
                "status": "ok",
                "size_bytes": len(result.audio_data),
                "format": result.audio_format.encoding.value,
                "provider": result.provider,
                "duration_ms": result.duration_ms,
                "artifact_path": file_path,
            }

        # Backward compat: if ElevenLabs transport is configured, use it
        if el_transport is not None:
            try:
                audio_data = await el_transport.synthesize(
                    body.text,
                    voice_id=body.voice_id or None,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except ElevenLabsTransportError as exc:
                raise HTTPException(
                    status_code=exc.status_code or 502,
                    detail=exc.detail or str(exc),
                ) from exc

            file_path = ""
            if body.session_id:
                file_path = el_store.save_audio(
                    session_id=body.session_id,
                    text=body.text,
                    audio_data=audio_data,
                    audio_format=el_config.output_format.split("_")[0],
                )
            return {
                "status": "ok",
                "size_bytes": len(audio_data),
                "format": el_config.output_format,
                "provider": "elevenlabs",
                "duration_ms": 0.0,
                "artifact_path": file_path,
            }

        # Stub result
        return {
            "status": "ok",
            "size_bytes": len(result.audio_data),
            "format": result.audio_format.encoding.value,
            "provider": result.provider,
            "duration_ms": result.duration_ms,
            "artifact_path": "",
        }

    # ------------------------------------------------------------------
    # Provider-agnostic STT endpoint (Phase 35)
    # ------------------------------------------------------------------

    @app.post("/v1/voice/transcribe")
    async def transcribe(
        file: UploadFile | None = None,
        language: str = Form(""),
        session_id: str = Form(""),
    ) -> dict[str, Any]:
        """Transcribe audio to text using the configured STT provider.

        Accepts multipart file upload. The ``file`` field should contain
        raw audio bytes.
        """
        if file is None:
            raise HTTPException(status_code=400, detail="audio file is required")

        audio_data = await file.read()
        if not audio_data:
            raise HTTPException(status_code=400, detail="audio file must not be empty")

        try:
            result = await resolved_service.transcribe(
                audio_data,
                language=language,
                session_id=session_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "status": "ok",
            "text": result.text,
            "confidence": result.confidence,
            "language": result.language,
            "provider": result.provider,
            "duration_ms": result.duration_ms,
            "is_partial": result.is_partial,
        }

    # ------------------------------------------------------------------
    # Voice listing (provider-agnostic + ElevenLabs fallback)
    # ------------------------------------------------------------------

    @app.get("/v1/voice/voices")
    async def list_voices() -> dict[str, Any]:
        """List available voices from the configured TTS provider."""
        tts = resolved_service.tts_provider
        try:
            voices = await tts.list_voices()
        except Exception:
            voices = []

        # Append ElevenLabs voices if transport is configured and provider
        # is not already elevenlabs
        if el_transport is not None and tts.provider_name != "elevenlabs":
            try:
                el_voices = await el_transport.list_voices()
                voices.extend(el_voices)
            except ElevenLabsTransportError:
                pass

        return {"voices": voices}

    @app.get("/v1/voice/health/elevenlabs")
    async def elevenlabs_health() -> dict[str, Any]:
        """Check ElevenLabs API connectivity."""
        if el_transport is None:
            return {
                "status": "unconfigured",
                "detail": "ElevenLabs API key is not set",
            }
        healthy = await el_transport.health_check()
        return {
            "status": "ok" if healthy else "unavailable",
            "model_id": el_config.model_id,
            "voice_id": el_config.voice_id,
        }

    @app.get("/v1/voice/health/providers")
    async def providers_health() -> dict[str, Any]:
        """Check health of configured TTS and STT providers."""
        tts_healthy = await resolved_service.tts_provider.health_check()
        stt_healthy = await resolved_service.stt_provider.health_check()
        return {
            "tts": {
                "provider": resolved_service.tts_provider.provider_name,
                "healthy": tts_healthy,
            },
            "stt": {
                "provider": resolved_service.stt_provider.provider_name,
                "healthy": stt_healthy,
            },
        }

    # ------------------------------------------------------------------
    # LiveKit endpoints (S32)
    # ------------------------------------------------------------------

    @app.post("/v1/voice/livekit/rooms", status_code=201)
    async def create_livekit_room(body: CreateLiveKitRoomRequest) -> dict[str, Any]:
        """Create a LiveKit room in the sidecar."""
        if lk_transport is None:
            raise HTTPException(
                status_code=503,
                detail="LiveKit transport is not configured",
            )
        try:
            room = lk_transport.create_room(body.name, metadata=body.metadata)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LiveKitTransportError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return room.to_dict()

    @app.get("/v1/voice/livekit/rooms")
    async def list_livekit_rooms() -> list[dict[str, Any]]:
        """List active LiveKit rooms."""
        if lk_transport is None:
            raise HTTPException(
                status_code=503,
                detail="LiveKit transport is not configured",
            )
        return [room.to_dict() for room in lk_transport.list_rooms()]

    @app.delete("/v1/voice/livekit/rooms/{name}")
    async def delete_livekit_room(name: str) -> dict[str, Any]:
        """Delete a LiveKit room."""
        if lk_transport is None:
            raise HTTPException(
                status_code=503,
                detail="LiveKit transport is not configured",
            )
        deleted = lk_transport.delete_room(name)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Room '{name}' not found")
        return {"status": "deleted", "room_name": name}

    @app.post("/v1/voice/livekit/token")
    async def generate_livekit_token(body: GenerateLiveKitTokenRequest) -> dict[str, Any]:
        """Generate a LiveKit access token."""
        if lk_transport is None:
            raise HTTPException(
                status_code=503,
                detail="LiveKit transport is not configured",
            )
        try:
            token = lk_transport.generate_token(
                body.room_name,
                body.identity,
                ttl=body.ttl,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except LiveKitTransportError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {"token": token, "room_name": body.room_name, "identity": body.identity}

    @app.get("/v1/voice/livekit/rooms/{name}/participants")
    async def list_livekit_participants(name: str) -> list[dict[str, Any]]:
        """List participants in a LiveKit room."""
        if lk_transport is None:
            raise HTTPException(
                status_code=503,
                detail="LiveKit transport is not configured",
            )
        try:
            participants = lk_transport.get_participants(name)
        except LiveKitTransportError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [p.to_dict() for p in participants]

    @app.get("/v1/voice/health/livekit")
    async def livekit_health() -> dict[str, Any]:
        """Check LiveKit transport configuration and connectivity."""
        if lk_transport is None:
            return {
                "status": "unconfigured",
                "detail": "LiveKit transport is not configured",
            }
        healthy = lk_transport.health_check()
        snap = lk_transport.snapshot()
        return {
            "status": "ok" if healthy else "unavailable",
            "ws_url": lk_config.ws_url,
            "default_codec": lk_config.default_codec,
            "active_rooms": snap["active_rooms"],
            "total_participants": snap["total_participants"],
        }

    return app
