"""In-memory multimodal orchestration service."""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

from agent33.multimodal.adapters import MultimodalAdapter, STTAdapter, TTSAdapter, VisionAdapter
from agent33.multimodal.models import (
    ModalityType,
    MultimodalPolicy,
    MultimodalRequest,
    MultimodalResult,
    RequestState,
    VoiceSession,
    VoiceSessionHealth,
    VoiceSessionState,
)
from agent33.multimodal.voice_daemon import VOICE_LIVEKIT_DEFERRED_MESSAGE, LiveVoiceDaemon

logger = logging.getLogger(__name__)

_ROOM_COMPONENT_PATTERN = re.compile(r"[^a-z0-9-]+")
_ROOM_DASH_PATTERN = re.compile(r"-+")
_ROOM_COMPONENT_LIMIT = 48
_VOICE_START_FAILURE_MESSAGE = "voice runtime could not start session"


class VoiceDaemonProtocol(Protocol):
    """Shared interface for the in-process shim and the standalone sidecar client."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def health_check(self) -> bool: ...

    async def process_audio_chunk(self, chunk: bytes) -> str | None: ...

    async def synthesize_speech(self, text: str) -> bytes | None: ...

    def snapshot(self) -> dict[str, object]: ...


class PolicyViolationError(Exception):
    """Raised when a request violates tenant multimodal policy."""


class RequestNotFoundError(Exception):
    """Raised when a multimodal request is not found."""


class InvalidStateTransitionError(Exception):
    """Raised when a request lifecycle transition is invalid."""


class VoiceRuntimeUnavailableError(Exception):
    """Raised when the live voice runtime is disabled or misconfigured."""


class MultimodalService:
    """Manage multimodal requests, execution, and policy enforcement."""

    def __init__(self) -> None:
        self._requests: dict[str, MultimodalRequest] = {}
        self._results: dict[str, MultimodalResult] = {}
        self._policies: dict[str, MultimodalPolicy] = {}
        self._voice_sessions: dict[str, VoiceSession] = {}
        self._voice_daemons: dict[str, VoiceDaemonProtocol] = {}
        self._voice_lock = asyncio.Lock()
        self._voice_runtime_enabled = True
        self._voice_transport = "stub"
        self._voice_url = ""
        self._voice_api_key = ""
        self._voice_api_secret = ""
        self._voice_room_prefix = "agent33-voice"
        self._voice_max_sessions = 25
        self._voice_daemon_factory: Callable[..., VoiceDaemonProtocol] = LiveVoiceDaemon
        self._adapters: dict[ModalityType, MultimodalAdapter] = {
            ModalityType.SPEECH_TO_TEXT: STTAdapter(),
            ModalityType.TEXT_TO_SPEECH: TTSAdapter(),
            ModalityType.VISION: VisionAdapter(),
        }

    def configure_voice_runtime(
        self,
        *,
        enabled: bool,
        transport: str,
        url: str,
        api_key: str,
        api_secret: str,
        room_prefix: str,
        max_sessions: int,
        daemon_factory: Callable[..., VoiceDaemonProtocol] | None = None,
    ) -> None:
        """Configure the runtime backing tenant-scoped voice sessions."""
        self._voice_runtime_enabled = enabled
        self._voice_transport = transport.strip().lower()
        self._voice_url = url
        self._voice_api_key = api_key
        self._voice_api_secret = api_secret
        self._voice_room_prefix = room_prefix or "agent33-voice"
        self._voice_max_sessions = max_sessions
        self._voice_daemon_factory = daemon_factory or LiveVoiceDaemon

    def set_policy(self, tenant_id: str, policy: MultimodalPolicy) -> None:
        self._policies[tenant_id] = policy

    def get_policy(self, tenant_id: str) -> MultimodalPolicy:
        return self._policies.get(tenant_id, MultimodalPolicy())

    def create_request(
        self,
        *,
        tenant_id: str,
        modality: ModalityType,
        input_text: str = "",
        input_artifact_id: str = "",
        input_artifact_base64: str = "",
        requested_timeout_seconds: int = 60,
        requested_by: str = "",
    ) -> MultimodalRequest:
        policy = self.get_policy(tenant_id)
        self._validate_policy(
            policy=policy,
            modality=modality,
            input_text=input_text,
            input_artifact_base64=input_artifact_base64,
            requested_timeout_seconds=requested_timeout_seconds,
        )
        request = MultimodalRequest(
            tenant_id=tenant_id,
            modality=modality,
            input_text=input_text,
            input_artifact_id=input_artifact_id,
            input_artifact_base64=input_artifact_base64,
            requested_timeout_seconds=requested_timeout_seconds,
            requested_by=requested_by,
        )
        self._requests[request.id] = request
        return request

    def list_requests(
        self,
        *,
        tenant_id: str | None = None,
        modality: ModalityType | None = None,
        state: RequestState | None = None,
        limit: int = 50,
    ) -> list[MultimodalRequest]:
        requests = list(self._requests.values())
        if tenant_id is not None:
            requests = [req for req in requests if req.tenant_id == tenant_id]
        if modality is not None:
            requests = [req for req in requests if req.modality == modality]
        if state is not None:
            requests = [req for req in requests if req.state == state]
        requests.sort(key=lambda req: req.created_at, reverse=True)
        return requests[:limit]

    def get_request(self, request_id: str, *, tenant_id: str | None = None) -> MultimodalRequest:
        request = self._requests.get(request_id)
        if request is None:
            raise RequestNotFoundError(f"Request not found: {request_id}")
        if tenant_id is not None and request.tenant_id != tenant_id:
            raise RequestNotFoundError(f"Request not found: {request_id}")
        return request

    async def execute_request(
        self, request_id: str, *, tenant_id: str | None = None
    ) -> MultimodalRequest:
        request = self.get_request(request_id, tenant_id=tenant_id)
        if request.state in (RequestState.COMPLETED, RequestState.CANCELLED):
            raise InvalidStateTransitionError(
                f"Cannot execute request in state '{request.state.value}'"
            )
        request.state = RequestState.PROCESSING
        request.updated_at = datetime.now(UTC)
        started_at = request.updated_at

        adapter = self._adapters[request.modality]
        try:
            output = await adapter.run(request)
        except Exception as exc:
            request.state = RequestState.FAILED
            request.error_message = str(exc)
            request.updated_at = datetime.now(UTC)
            result = MultimodalResult(
                request_id=request.id,
                state=RequestState.FAILED,
                started_at=started_at,
                completed_at=request.updated_at,
                metadata={"error": str(exc)},
            )
            self._results[result.id] = result
            request.result_id = result.id
            return request

        request.state = RequestState.COMPLETED
        request.updated_at = datetime.now(UTC)
        result = MultimodalResult(
            request_id=request.id,
            state=RequestState.COMPLETED,
            output_text=output.get("output_text", ""),
            output_artifact_id=output.get("output_artifact_id", ""),
            output_data=output.get("output_data", {}),
            started_at=started_at,
            completed_at=request.updated_at,
        )
        self._results[result.id] = result
        request.result_id = result.id
        request.error_message = ""
        return request

    def get_result(self, request_id: str, *, tenant_id: str | None = None) -> MultimodalResult:
        request = self.get_request(request_id, tenant_id=tenant_id)
        if not request.result_id:
            raise RequestNotFoundError(f"Result not available for request: {request_id}")
        result = self._results.get(request.result_id)
        if result is None:
            raise RequestNotFoundError(f"Result not available for request: {request_id}")
        return result

    def cancel_request(
        self, request_id: str, *, tenant_id: str | None = None
    ) -> MultimodalRequest:
        request = self.get_request(request_id, tenant_id=tenant_id)
        if request.state in (RequestState.COMPLETED, RequestState.FAILED):
            raise InvalidStateTransitionError(
                f"Cannot cancel request in state '{request.state.value}'"
            )
        request.state = RequestState.CANCELLED
        request.error_message = "Cancelled by operator"
        request.updated_at = datetime.now(UTC)
        return request

    async def start_voice_session(
        self,
        *,
        tenant_id: str,
        requested_by: str = "",
        room_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> VoiceSession:
        async with self._voice_lock:
            resolved_tenant_id = tenant_id.strip()
            if not resolved_tenant_id:
                raise PolicyViolationError("voice sessions require tenant context")
            policy = self.get_policy(resolved_tenant_id)
            self._validate_voice_runtime(policy=policy, tenant_id=resolved_tenant_id)

            active_sessions = [
                session
                for session in self._voice_sessions.values()
                if session.tenant_id == resolved_tenant_id
                and session.state in {VoiceSessionState.STARTING, VoiceSessionState.ACTIVE}
            ]
            if len(active_sessions) >= policy.max_voice_concurrent_sessions:
                raise PolicyViolationError(
                    "voice session limit exceeded for tenant policy "
                    f"({policy.max_voice_concurrent_sessions})"
                )
            if len(self._voice_daemons) >= self._voice_max_sessions:
                raise VoiceRuntimeUnavailableError("voice runtime is at global capacity")

            session = VoiceSession(
                tenant_id=resolved_tenant_id,
                room_name=self._build_room_name(resolved_tenant_id, room_name),
                requested_by=requested_by,
                transport=self._voice_transport,
                max_duration_seconds=policy.max_voice_session_seconds,
                metadata=metadata or {},
            )
            self._voice_sessions[session.id] = session

            daemon = self._voice_daemon_factory(
                room_name=session.room_name,
                url=self._voice_url,
                api_key=self._voice_api_key,
                api_secret=self._voice_api_secret,
                transport=self._voice_transport,
            )
            try:
                await daemon.start()
            except Exception as exc:
                logger.exception(
                    "voice session start failed for tenant %s room %s",
                    resolved_tenant_id,
                    session.room_name,
                )
                session.state = VoiceSessionState.FAILED
                session.last_error = _VOICE_START_FAILURE_MESSAGE
                session.updated_at = datetime.now(UTC)
                raise VoiceRuntimeUnavailableError(_VOICE_START_FAILURE_MESSAGE) from exc

            self._voice_daemons[session.id] = daemon
            session.state = VoiceSessionState.ACTIVE
            session.daemon_health = daemon.health_check()
            session.started_at = datetime.now(UTC)
            session.updated_at = session.started_at
            return session

    def list_voice_sessions(
        self,
        *,
        tenant_id: str | None = None,
        state: VoiceSessionState | None = None,
        limit: int = 50,
    ) -> list[VoiceSession]:
        sessions = list(self._voice_sessions.values())
        if tenant_id is not None:
            sessions = [session for session in sessions if session.tenant_id == tenant_id]
        if state is not None:
            sessions = [session for session in sessions if session.state == state]
        sessions.sort(key=lambda session: session.created_at, reverse=True)
        return sessions[:limit]

    def get_voice_session(
        self,
        session_id: str,
        *,
        tenant_id: str | None = None,
    ) -> VoiceSession:
        session = self._require_voice_session(session_id, tenant_id=tenant_id)
        return session.model_copy(update={"daemon_health": self._voice_session_health(session_id)})

    def get_voice_session_health(
        self,
        session_id: str,
        *,
        tenant_id: str | None = None,
    ) -> VoiceSessionHealth:
        session = self._require_voice_session(session_id, tenant_id=tenant_id)
        daemon = self._voice_daemons.get(session_id)
        healthy = daemon.health_check() if daemon is not None else False
        details = daemon.snapshot() if daemon is not None else {}
        return VoiceSessionHealth(
            session_id=session.id,
            room_name=session.room_name,
            state=session.state,
            transport=session.transport,
            healthy=healthy,
            details=details,
        )

    async def stop_voice_session(
        self,
        session_id: str,
        *,
        tenant_id: str | None = None,
    ) -> VoiceSession:
        async with self._voice_lock:
            session = self._require_voice_session(session_id, tenant_id=tenant_id)
            if session.state == VoiceSessionState.STOPPED:
                return session

            daemon = self._voice_daemons.get(session_id)
            session.state = VoiceSessionState.STOPPING
            session.updated_at = datetime.now(UTC)
            if daemon is not None:
                await daemon.stop()
                session.daemon_health = daemon.health_check()
                self._voice_daemons.pop(session_id, None)
            session.state = VoiceSessionState.STOPPED
            session.stopped_at = datetime.now(UTC)
            session.updated_at = session.stopped_at
            return session

    async def shutdown_voice_sessions(self) -> None:
        """Stop all active daemons during application shutdown."""
        async with self._voice_lock:
            for session_id in list(self._voice_daemons.keys()):
                session = self._voice_sessions.get(session_id)
                daemon = self._voice_daemons.pop(session_id)
                await daemon.stop()
                if session is not None:
                    session.state = VoiceSessionState.STOPPED
                    session.daemon_health = False
                    session.stopped_at = datetime.now(UTC)
                    session.updated_at = session.stopped_at

    def _validate_policy(
        self,
        *,
        policy: MultimodalPolicy,
        modality: ModalityType,
        input_text: str,
        input_artifact_base64: str,
        requested_timeout_seconds: int,
    ) -> None:
        if modality not in policy.allowed_modalities:
            raise PolicyViolationError(f"Modality '{modality.value}' is not allowed")
        if len(input_text) > policy.max_text_chars:
            raise PolicyViolationError("input_text exceeds tenant max_text_chars policy")
        if requested_timeout_seconds > policy.max_timeout_seconds:
            raise PolicyViolationError("requested_timeout_seconds exceeds tenant timeout policy")

        artifact_bytes = self._artifact_size(input_artifact_base64)
        if artifact_bytes > policy.max_artifact_bytes:
            raise PolicyViolationError("input artifact exceeds tenant max_artifact_bytes policy")

    def _validate_voice_runtime(self, *, policy: MultimodalPolicy, tenant_id: str) -> None:
        if not self._voice_runtime_enabled:
            raise VoiceRuntimeUnavailableError("voice runtime is disabled")
        if not policy.voice_enabled:
            raise PolicyViolationError(f"voice sessions are disabled for tenant '{tenant_id}'")
        if policy.max_voice_concurrent_sessions <= 0:
            raise PolicyViolationError("voice sessions are disabled by tenant concurrency policy")
        if self._voice_transport == "livekit":
            raise VoiceRuntimeUnavailableError(VOICE_LIVEKIT_DEFERRED_MESSAGE)

    def _require_voice_session(
        self,
        session_id: str,
        *,
        tenant_id: str | None = None,
    ) -> VoiceSession:
        session = self._voice_sessions.get(session_id)
        if session is None:
            raise RequestNotFoundError(f"Voice session not found: {session_id}")
        if tenant_id is not None and session.tenant_id != tenant_id:
            raise RequestNotFoundError(f"Voice session not found: {session_id}")
        return session

    def _voice_session_health(self, session_id: str) -> bool:
        daemon = self._voice_daemons.get(session_id)
        return daemon.health_check() if daemon is not None else False

    def _build_room_name(self, tenant_id: str, requested_room_name: str = "") -> str:
        prefix = self._normalize_room_component(self._voice_room_prefix, fallback="agent33-voice")
        sanitized_tenant = self._normalize_room_component(tenant_id, fallback="tenant")
        label = self._normalize_room_component(requested_room_name, fallback="session")
        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        return f"{prefix}-{sanitized_tenant}-{label}-{timestamp}"

    @staticmethod
    def _normalize_room_component(value: str, *, fallback: str) -> str:
        normalized = value.strip().lower()
        normalized = _ROOM_COMPONENT_PATTERN.sub("-", normalized)
        normalized = _ROOM_DASH_PATTERN.sub("-", normalized).strip("-")
        if not normalized:
            return fallback
        truncated = normalized[:_ROOM_COMPONENT_LIMIT].strip("-")
        return truncated or fallback

    @staticmethod
    def _artifact_size(input_artifact_base64: str) -> int:
        if not input_artifact_base64:
            return 0
        try:
            decoded = base64.b64decode(input_artifact_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PolicyViolationError("input_artifact_base64 is invalid base64") from exc
        return len(decoded)
