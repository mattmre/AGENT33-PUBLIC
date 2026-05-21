"""Domain models for multimodal request/response lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ModalityType(StrEnum):
    """Supported multimodal operations."""

    SPEECH_TO_TEXT = "speech_to_text"
    TEXT_TO_SPEECH = "text_to_speech"
    VISION = "vision_analysis"


class RequestState(StrEnum):
    """Lifecycle state for multimodal requests."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class VoiceSessionState(StrEnum):
    """Lifecycle state for a live voice daemon session."""

    STARTING = "starting"
    ACTIVE = "active"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class MultimodalPolicy(BaseModel):
    """Per-tenant multimodal policy limits.

    Controls resource consumption and access for multimodal operations on a
    per-tenant basis.  Every tenant receives the *default* policy unless an
    operator explicitly overrides it via ``MultimodalService.set_policy``.
    """

    max_text_chars: int = Field(
        default=5000,
        ge=0,
        description=(
            "Upper bound on input text length (characters).  5 000 chars ≈ "
            "~1 250 tokens — sufficient for most TTS prompts while preventing "
            "accidental megabyte-scale payloads."
        ),
    )
    max_artifact_bytes: int = Field(
        default=5_000_000,
        ge=0,
        description=(
            "Upper bound on decoded binary artifact size (bytes).  5 MB "
            "accommodates a high-quality JPEG or a short audio clip without "
            "risking memory pressure on the worker."
        ),
    )
    max_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description=(
            "Maximum wall-clock time allowed for a single multimodal request.  "
            "300 s (5 min) covers slow Vision-Language Model inference while "
            "still bounding runaway operations."
        ),
    )
    allowed_modalities: set[ModalityType] = Field(
        default_factory=lambda: {
            ModalityType.SPEECH_TO_TEXT,
            ModalityType.TEXT_TO_SPEECH,
            ModalityType.VISION,
        },
        description=(
            "Set of modalities the tenant is permitted to invoke.  Defaults to "
            "all three; operators can restrict access for cost control or "
            "compliance reasons."
        ),
    )
    voice_enabled: bool = Field(
        default=True,
        description=(
            "Whether the tenant may start long-lived live voice daemon sessions. "
            "Enabled by default for the built-in stub transport so operators can "
            "exercise the control plane without external media infrastructure."
        ),
    )
    max_voice_concurrent_sessions: int = Field(
        default=1,
        ge=0,
        description=(
            "Upper bound on simultaneously active live voice sessions for a tenant. "
            "Defaulting to one avoids accidental fan-out of long-lived audio workers."
        ),
    )
    max_voice_session_seconds: int = Field(
        default=1800,
        ge=1,
        description=(
            "Recorded voice-session duration budget for operator guidance and future "
            "runtime enforcement. The current stub runtime stores this value on the "
            "session record but does not auto-expire active sessions yet."
        ),
    )


# ---------------------------------------------------------------------------
# Recommended per-modality policy configurations
# ---------------------------------------------------------------------------
# These are *advisory* presets.  They are NOT enforced automatically — callers
# or deployment tooling can merge them into tenant policies as a starting
# point.  Each preset tightens defaults to match the expected resource profile
# of its modality.
# ---------------------------------------------------------------------------

RECOMMENDED_POLICIES: dict[str, MultimodalPolicy] = {
    "stt": MultimodalPolicy(
        max_text_chars=0,
        max_artifact_bytes=10_000_000,
        max_timeout_seconds=120,
        allowed_modalities={ModalityType.SPEECH_TO_TEXT},
    ),
    "tts": MultimodalPolicy(
        max_text_chars=10_000,
        max_artifact_bytes=0,
        max_timeout_seconds=60,
        allowed_modalities={ModalityType.TEXT_TO_SPEECH},
    ),
    "vision": MultimodalPolicy(
        max_text_chars=2000,
        max_artifact_bytes=20_000_000,
        max_timeout_seconds=300,
        allowed_modalities={ModalityType.VISION},
    ),
    "voice": MultimodalPolicy(
        max_text_chars=10_000,
        max_artifact_bytes=10_000_000,
        max_timeout_seconds=120,
        allowed_modalities={
            ModalityType.SPEECH_TO_TEXT,
            ModalityType.TEXT_TO_SPEECH,
        },
        voice_enabled=True,
        max_voice_concurrent_sessions=1,
        max_voice_session_seconds=1800,
    ),
}


class MultimodalRequest(BaseModel):
    """Request record for multimodal processing."""

    id: str = Field(default_factory=lambda: _id("mmreq"))
    tenant_id: str = ""
    modality: ModalityType
    input_text: str = ""
    input_artifact_id: str = ""
    input_artifact_base64: str = ""
    requested_timeout_seconds: int = 60
    requested_by: str = ""
    state: RequestState = RequestState.PENDING
    result_id: str = ""
    error_message: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MultimodalResult(BaseModel):
    """Execution result for a multimodal request."""

    id: str = Field(default_factory=lambda: _id("mmres"))
    request_id: str
    state: RequestState
    output_text: str = ""
    output_artifact_id: str = ""
    output_data: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceSession(BaseModel):
    """Tenant-scoped live voice session tracked by the multimodal service."""

    id: str = Field(default_factory=lambda: _id("vcs"))
    tenant_id: str = ""
    room_name: str
    requested_by: str = ""
    state: VoiceSessionState = VoiceSessionState.STARTING
    transport: str = "stub"
    daemon_health: bool = False
    max_duration_seconds: int = 1800
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    last_error: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class VoiceSessionHealth(BaseModel):
    """Health probe result for a live voice session."""

    session_id: str
    room_name: str
    state: VoiceSessionState
    transport: str
    healthy: bool
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = Field(default_factory=dict)
