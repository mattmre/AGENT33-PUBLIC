"""Models for the standalone voice sidecar."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class VoiceSidecarSessionState(StrEnum):
    """Lifecycle state for standalone sidecar sessions."""

    ACTIVE = "active"
    STOPPED = "stopped"


class VoicePersona(BaseModel):
    """Configured voice persona loaded from ``voices.json``."""

    id: str
    name: str
    provider: str = "stub"
    voice_id: str = ""
    style: str = "balanced"
    description: str = ""


class AudioFormatConfig(BaseModel):
    """Audio format settings attached to a voice session.

    Phase 35: allows callers to specify the desired wire format
    for TTS output and STT input within a session.
    """

    encoding: str = "pcm_s16le"
    sample_rate: int = 16000
    channels: int = 1
    bit_depth: int = 16


class VoiceSidecarSession(BaseModel):
    """Runtime state for a standalone sidecar session."""

    session_id: str
    room_name: str
    requested_by: str = ""
    persona_id: str = "default"
    state: VoiceSidecarSessionState = VoiceSidecarSessionState.ACTIVE
    transport: str = "sidecar"
    metadata: dict[str, Any] = Field(default_factory=dict)
    websocket_connections: int = 0
    artifacts_path: str = ""
    audio_format: AudioFormatConfig = Field(default_factory=AudioFormatConfig)
    agent_session_id: str = ""
    tts_provider: str = "stub"
    stt_provider: str = "stub"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    stopped_at: datetime | None = None
    last_error: str = ""


class VoiceSidecarHealth(BaseModel):
    """Health snapshot for the voice sidecar."""

    status: str = "healthy"
    service: str = "voice_sidecar"
    playback_backend: str = "noop"
    voices_path: str = ""
    artifacts_dir: str = ""
    persona_count: int = 0
    session_count: int = 0
    active_sessions: int = 0
    websocket_connections: int = 0
    tts_provider: str = "stub"
    stt_provider: str = "stub"
    shutting_down: bool = False
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
