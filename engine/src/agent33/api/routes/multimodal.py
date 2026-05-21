"""FastAPI routes for multimodal request lifecycle."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.api.routes.tenant_access import require_tenant_context, tenant_filter_for_request
from agent33.multimodal.models import (
    ModalityType,
    MultimodalPolicy,
    RequestState,
    VoiceSessionState,
)
from agent33.multimodal.service import (
    InvalidStateTransitionError,
    MultimodalService,
    PolicyViolationError,
    RequestNotFoundError,
    VoiceRuntimeUnavailableError,
)
from agent33.security.permissions import check_permission, require_scope

router = APIRouter(prefix="/v1/multimodal", tags=["multimodal"])
_service = MultimodalService()


class CreateRequestBody(BaseModel):
    modality: ModalityType
    input_text: str = ""
    input_artifact_id: str = ""
    input_artifact_base64: str = ""
    requested_timeout_seconds: int = Field(default=60, ge=1)
    requested_by: str = ""
    execute_now: bool = True


class CreateVoiceSessionBody(BaseModel):
    requested_by: str = ""
    room_name: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


def get_multimodal_service() -> MultimodalService:
    """Return singleton multimodal service."""
    return _service


def _tenant_id(request: Request) -> str:
    tenant_id, _ = require_tenant_context(request)
    return tenant_id


def _tenant_filter(request: Request) -> str | None:
    return tenant_filter_for_request(request)


def _voice_session_tenant_id(request: Request) -> str:
    tenant_id, _ = require_tenant_context(request)
    if not tenant_id:
        raise HTTPException(status_code=403, detail="Tenant context required for voice sessions")
    return tenant_id


@router.post("/requests", status_code=201, dependencies=[require_scope("multimodal:write")])
async def create_request(body: CreateRequestBody, request: Request) -> dict[str, Any]:
    tenant_id = _tenant_id(request)
    try:
        created = _service.create_request(
            tenant_id=tenant_id,
            modality=body.modality,
            input_text=body.input_text,
            input_artifact_id=body.input_artifact_id,
            input_artifact_base64=body.input_artifact_base64,
            requested_timeout_seconds=body.requested_timeout_seconds,
            requested_by=body.requested_by,
        )
        if body.execute_now:
            created = await _service.execute_request(created.id, tenant_id=tenant_id or None)
    except PolicyViolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return created.model_dump(mode="json")


@router.get("/requests", dependencies=[require_scope("multimodal:read")])
async def list_requests(
    request: Request,
    modality: ModalityType | None = None,
    state: RequestState | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    requests = _service.list_requests(
        tenant_id=_tenant_filter(request),
        modality=modality,
        state=state,
        limit=limit,
    )
    return [req.model_dump(mode="json") for req in requests]


@router.get("/requests/{request_id}", dependencies=[require_scope("multimodal:read")])
async def get_request(request_id: str, request: Request) -> dict[str, Any]:
    try:
        record = _service.get_request(request_id, tenant_id=_tenant_filter(request))
    except RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.post(
    "/requests/{request_id}/execute",
    dependencies=[require_scope("multimodal:write")],
)
async def execute_request(request_id: str, request: Request) -> dict[str, Any]:
    try:
        record = await _service.execute_request(request_id, tenant_id=_tenant_filter(request))
    except RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.get(
    "/requests/{request_id}/result",
    dependencies=[require_scope("multimodal:read")],
)
async def get_result(request_id: str, request: Request) -> dict[str, Any]:
    try:
        result = _service.get_result(request_id, tenant_id=_tenant_filter(request))
    except RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post(
    "/requests/{request_id}/cancel",
    dependencies=[require_scope("multimodal:write")],
)
async def cancel_request(request_id: str, request: Request) -> dict[str, Any]:
    try:
        record = _service.cancel_request(request_id, tenant_id=_tenant_filter(request))
    except RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return record.model_dump(mode="json")


@router.post(
    "/voice/sessions",
    status_code=201,
    dependencies=[require_scope("multimodal:write")],
)
async def start_voice_session(body: CreateVoiceSessionBody, request: Request) -> dict[str, Any]:
    tenant_id = _voice_session_tenant_id(request)
    try:
        session = await _service.start_voice_session(
            tenant_id=tenant_id,
            requested_by=body.requested_by,
            room_name=body.room_name,
            metadata=body.metadata,
        )
    except PolicyViolationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except VoiceRuntimeUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return session.model_dump(mode="json")


@router.get("/voice/sessions", dependencies=[require_scope("multimodal:read")])
async def list_voice_sessions(
    request: Request,
    state: VoiceSessionState | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    sessions = _service.list_voice_sessions(
        tenant_id=_tenant_filter(request),
        state=state,
        limit=limit,
    )
    return [session.model_dump(mode="json") for session in sessions]


@router.get("/voice/sessions/{session_id}", dependencies=[require_scope("multimodal:read")])
async def get_voice_session(session_id: str, request: Request) -> dict[str, Any]:
    try:
        session = _service.get_voice_session(session_id, tenant_id=_tenant_filter(request))
    except RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session.model_dump(mode="json")


@router.get(
    "/voice/sessions/{session_id}/health",
    dependencies=[require_scope("multimodal:read")],
)
async def get_voice_session_health(session_id: str, request: Request) -> dict[str, Any]:
    try:
        health = _service.get_voice_session_health(session_id, tenant_id=_tenant_filter(request))
    except RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return health.model_dump(mode="json")


@router.post(
    "/voice/sessions/{session_id}/stop",
    dependencies=[require_scope("multimodal:write")],
)
async def stop_voice_session(session_id: str, request: Request) -> dict[str, Any]:
    try:
        session = await _service.stop_voice_session(session_id, tenant_id=_tenant_filter(request))
    except RequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session.model_dump(mode="json")


@router.post(
    "/tenants/{tenant_id}/policy",
    dependencies=[require_scope("multimodal:write")],
)
async def set_tenant_policy(
    tenant_id: str, policy: MultimodalPolicy, request: Request
) -> dict[str, Any]:
    """Set policy guardrails for a tenant (Stage 1 helper endpoint)."""
    request_tenant_id, request_scopes = require_tenant_context(request)
    is_admin = check_permission("admin", request_scopes) if request_scopes else False
    if request_tenant_id and not is_admin and tenant_id != request_tenant_id:
        raise HTTPException(status_code=403, detail="Tenant mismatch for authenticated principal")
    resolved_tenant_id = tenant_id or request_tenant_id
    _service.set_policy(resolved_tenant_id, policy)
    return policy.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Voice feature health (M-05) — separate router, no /v1/multimodal prefix
# ---------------------------------------------------------------------------

voice_health_router = APIRouter(prefix="/v1/voice", tags=["voice"])


@voice_health_router.get("/health")
async def voice_health(request: Request) -> dict[str, Any]:  # noqa: ARG001
    """Return voice feature status based on provider configuration."""
    from agent33.config import settings

    is_stub = (
        settings.voice_daemon_transport == "stub"
        and settings.voice_tts_provider == "stub"
        and settings.voice_stt_provider == "stub"
    )
    return {
        "feature": "disabled" if is_stub else "enabled",
        "transport": settings.voice_daemon_transport,
        "tts_provider": settings.voice_tts_provider,
        "stt_provider": settings.voice_stt_provider,
    }
