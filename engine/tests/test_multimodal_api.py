"""Phase 29 Stage 1 tests for multimodal backend contracts."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agent33.api.routes.multimodal import _service
from agent33.main import app
from agent33.multimodal.models import (
    ModalityType,
    MultimodalPolicy,
    RequestState,
    VoiceSessionState,
)
from agent33.security.auth import create_access_token
from agent33.voice.app import create_voice_sidecar_app
from agent33.voice.client import SidecarVoiceDaemon, VoiceSidecarClient
from agent33.voice.service import VoiceSidecarService


@pytest.fixture(autouse=True)
def reset_multimodal_service() -> None:
    _service._requests.clear()
    _service._results.clear()
    _service._policies.clear()
    _service._voice_sessions.clear()
    _service._voice_daemons.clear()
    _service.configure_voice_runtime(
        enabled=True,
        transport="stub",
        url="",
        api_key="",
        api_secret="",
        room_prefix="agent33-voice",
        max_sessions=25,
    )
    yield
    _service._requests.clear()
    _service._results.clear()
    _service._policies.clear()
    _service._voice_sessions.clear()
    _service._voice_daemons.clear()


def _client(scopes: list[str], *, tenant_id: str = "tenant-a") -> TestClient:
    token = create_access_token("multimodal-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def writer_client() -> TestClient:
    return _client(["multimodal:read", "multimodal:write"])


@pytest.fixture
def reader_client() -> TestClient:
    return _client(["multimodal:read"])


@pytest.fixture
def no_scope_client() -> TestClient:
    return _client([])


@pytest.fixture
def tenant_b_writer() -> TestClient:
    return _client(["multimodal:read", "multimodal:write"], tenant_id="tenant-b")


@pytest.fixture
def admin_client() -> TestClient:
    return _client(["admin"], tenant_id="tenant-a")


def test_create_request_with_execute_now_false(writer_client: TestClient) -> None:
    response = writer_client.post(
        "/v1/multimodal/requests",
        json={
            "modality": "text_to_speech",
            "input_text": "hello",
            "execute_now": False,
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["state"] == "pending"
    assert payload["result_id"] == ""


def test_create_request_execute_now_true_completes(writer_client: TestClient) -> None:
    response = writer_client.post(
        "/v1/multimodal/requests",
        json={
            "modality": "text_to_speech",
            "input_text": "hello world",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["state"] == "completed"
    assert payload["result_id"] != ""


def test_create_request_requires_write_scope(reader_client: TestClient) -> None:
    response = reader_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "blocked"},
    )
    assert response.status_code == 403
    assert "multimodal:write" in response.json()["detail"]


def test_read_requests_require_read_scope(no_scope_client: TestClient) -> None:
    response = no_scope_client.get("/v1/multimodal/requests")
    assert response.status_code == 403
    assert "multimodal:read" in response.json()["detail"]


def test_policy_blocks_over_limit_text(writer_client: TestClient) -> None:
    writer_client.post(
        "/v1/multimodal/tenants/tenant-a/policy",
        json={"max_text_chars": 4},
    )
    response = writer_client.post(
        "/v1/multimodal/requests",
        json={
            "modality": "text_to_speech",
            "input_text": "this is too long",
            "execute_now": False,
        },
    )
    assert response.status_code == 400
    assert "max_text_chars" in response.json()["detail"]


def test_policy_blocks_over_limit_artifact(writer_client: TestClient) -> None:
    writer_client.post(
        "/v1/multimodal/tenants/tenant-a/policy",
        json={"max_artifact_bytes": 2},
    )
    encoded = base64.b64encode(b"abcdef").decode("utf-8")
    response = writer_client.post(
        "/v1/multimodal/requests",
        json={
            "modality": "vision_analysis",
            "input_artifact_base64": encoded,
            "execute_now": False,
        },
    )
    assert response.status_code == 400
    assert "max_artifact_bytes" in response.json()["detail"]


def test_policy_blocks_disallowed_modality(writer_client: TestClient) -> None:
    writer_client.post(
        "/v1/multimodal/tenants/tenant-a/policy",
        json={"allowed_modalities": ["vision_analysis"]},
    )
    response = writer_client.post(
        "/v1/multimodal/requests",
        json={
            "modality": "text_to_speech",
            "input_text": "should fail",
            "execute_now": False,
        },
    )
    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"]


def test_policy_route_rejects_cross_tenant_write_for_non_admin(
    writer_client: TestClient,
) -> None:
    response = writer_client.post(
        "/v1/multimodal/tenants/tenant-b/policy",
        json={"max_text_chars": 4},
    )
    assert response.status_code == 403
    assert "Tenant mismatch" in response.json()["detail"]


def test_create_request_rejects_authenticated_user_without_tenant_context() -> None:
    tenantless_client = _client(["multimodal:read", "multimodal:write"], tenant_id="")
    response = tenantless_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "blocked"},
    )
    assert response.status_code == 403
    assert "Tenant context required" in response.json()["detail"]


def test_list_requests_rejects_authenticated_user_without_tenant_context() -> None:
    tenantless_client = _client(["multimodal:read"], tenant_id="")
    response = tenantless_client.get("/v1/multimodal/requests")
    assert response.status_code == 403
    assert "Tenant context required" in response.json()["detail"]


def test_policy_route_rejects_authenticated_user_without_tenant_context() -> None:
    tenantless_client = _client(["multimodal:write"], tenant_id="")
    response = tenantless_client.post(
        "/v1/multimodal/tenants/tenant-a/policy",
        json={"max_text_chars": 4},
    )
    assert response.status_code == 403
    assert "Tenant context required" in response.json()["detail"]


def test_policy_route_allows_admin_cross_tenant_write(
    admin_client: TestClient,
    tenant_b_writer: TestClient,
) -> None:
    response = admin_client.post(
        "/v1/multimodal/tenants/tenant-b/policy",
        json={"max_text_chars": 4},
    )
    assert response.status_code == 200

    blocked = tenant_b_writer.post(
        "/v1/multimodal/requests",
        json={
            "modality": "text_to_speech",
            "input_text": "this is too long",
            "execute_now": False,
        },
    )
    assert blocked.status_code == 400
    assert "max_text_chars" in blocked.json()["detail"]


def test_list_requests_is_tenant_scoped(
    writer_client: TestClient, tenant_b_writer: TestClient
) -> None:
    writer_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "tenant-a", "execute_now": False},
    )
    tenant_b_writer.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "tenant-b", "execute_now": False},
    )

    tenant_a_items = writer_client.get("/v1/multimodal/requests").json()
    tenant_b_items = tenant_b_writer.get("/v1/multimodal/requests").json()

    assert len(tenant_a_items) == 1
    assert len(tenant_b_items) == 1
    assert tenant_a_items[0]["tenant_id"] == "tenant-a"
    assert tenant_b_items[0]["tenant_id"] == "tenant-b"


def test_get_request_is_tenant_scoped(
    writer_client: TestClient, tenant_b_writer: TestClient
) -> None:
    create_response = writer_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "tenant-a", "execute_now": False},
    )
    request_id = create_response.json()["id"]

    allowed = writer_client.get(f"/v1/multimodal/requests/{request_id}")
    denied = tenant_b_writer.get(f"/v1/multimodal/requests/{request_id}")
    assert allowed.status_code == 200
    assert denied.status_code == 404


def test_execute_request_transitions_state(writer_client: TestClient) -> None:
    create_response = writer_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "run", "execute_now": False},
    )
    request_id = create_response.json()["id"]

    execute_response = writer_client.post(f"/v1/multimodal/requests/{request_id}/execute")
    assert execute_response.status_code == 200
    assert execute_response.json()["state"] == "completed"


def test_execute_request_route_uses_adapter_run_async(writer_client: TestClient) -> None:
    create_response = writer_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "run-async-only", "execute_now": False},
    )
    request_id = create_response.json()["id"]

    class _AsyncRunAdapter:
        """Mock adapter with async run() matching the current MultimodalAdapter protocol."""

        def __init__(self) -> None:
            self.run_calls = 0

        async def run(self, _request: object) -> dict[str, object]:
            self.run_calls += 1
            return {
                "output_text": "",
                "output_artifact_id": "artifact-run-async-only",
                "output_data": {
                    "modality": ModalityType.TEXT_TO_SPEECH.value,
                    "test": "run_async",
                },
            }

    original_adapter = _service._adapters[ModalityType.TEXT_TO_SPEECH]
    adapter = _AsyncRunAdapter()
    _service._adapters[ModalityType.TEXT_TO_SPEECH] = adapter
    try:
        execute_response = writer_client.post(f"/v1/multimodal/requests/{request_id}/execute")
        assert execute_response.status_code == 200
        assert execute_response.json()["state"] == "completed"
        assert adapter.run_calls == 1
    finally:
        _service._adapters[ModalityType.TEXT_TO_SPEECH] = original_adapter


def test_execute_request_requires_write_scope(
    writer_client: TestClient, reader_client: TestClient
) -> None:
    create_response = writer_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "run", "execute_now": False},
    )
    request_id = create_response.json()["id"]
    response = reader_client.post(f"/v1/multimodal/requests/{request_id}/execute")
    assert response.status_code == 403


def test_get_result_returns_404_when_not_available(writer_client: TestClient) -> None:
    create_response = writer_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "pending", "execute_now": False},
    )
    request_id = create_response.json()["id"]
    response = writer_client.get(f"/v1/multimodal/requests/{request_id}/result")
    assert response.status_code == 404


def test_get_result_after_execution(writer_client: TestClient) -> None:
    create_response = writer_client.post(
        "/v1/multimodal/requests",
        json={
            "modality": "vision_analysis",
            "input_artifact_base64": base64.b64encode(b"x").decode(),
        },
    )
    request_id = create_response.json()["id"]

    response = writer_client.get(f"/v1/multimodal/requests/{request_id}/result")
    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == request_id
    assert payload["state"] == "completed"


def test_cancel_pending_request(writer_client: TestClient) -> None:
    create_response = writer_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "cancel", "execute_now": False},
    )
    request_id = create_response.json()["id"]

    cancel_response = writer_client.post(f"/v1/multimodal/requests/{request_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["state"] == "cancelled"


def test_cancel_completed_request_returns_409(writer_client: TestClient) -> None:
    create_response = writer_client.post(
        "/v1/multimodal/requests",
        json={"modality": "text_to_speech", "input_text": "already-complete"},
    )
    request_id = create_response.json()["id"]
    cancel_response = writer_client.post(f"/v1/multimodal/requests/{request_id}/cancel")
    assert cancel_response.status_code == 409


async def test_service_policy_and_lifecycle_contracts() -> None:
    _service.set_policy(
        "tenant-a",
        MultimodalPolicy(allowed_modalities={ModalityType.TEXT_TO_SPEECH}, max_text_chars=10),
    )
    request = _service.create_request(
        tenant_id="tenant-a",
        modality=ModalityType.TEXT_TO_SPEECH,
        input_text="short",
        requested_timeout_seconds=5,
    )
    assert request.state == RequestState.PENDING
    request = await _service.execute_request(request.id, tenant_id="tenant-a")
    assert request.state == RequestState.COMPLETED


def test_start_voice_session_returns_active_stub_session(writer_client: TestClient) -> None:
    response = writer_client.post(
        "/v1/multimodal/voice/sessions",
        json={"requested_by": "operator"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["state"] == "active"
    assert payload["transport"] == "stub"
    assert payload["daemon_health"] is True
    assert payload["requested_by"] == "operator"
    assert payload["room_name"].startswith("agent33-voice-tenant-a-session-")


def test_list_voice_sessions_is_tenant_scoped(
    writer_client: TestClient, tenant_b_writer: TestClient
) -> None:
    session_a = writer_client.post("/v1/multimodal/voice/sessions", json={})
    session_b = tenant_b_writer.post("/v1/multimodal/voice/sessions", json={})

    tenant_a_items = writer_client.get("/v1/multimodal/voice/sessions").json()
    tenant_b_items = tenant_b_writer.get("/v1/multimodal/voice/sessions").json()

    assert session_a.status_code == 201
    assert session_b.status_code == 201
    assert len(tenant_a_items) == 1
    assert len(tenant_b_items) == 1
    assert tenant_a_items[0]["tenant_id"] == "tenant-a"
    assert tenant_b_items[0]["tenant_id"] == "tenant-b"


def test_admin_can_list_voice_sessions_across_tenants(
    writer_client: TestClient,
    tenant_b_writer: TestClient,
    admin_client: TestClient,
) -> None:
    writer_client.post("/v1/multimodal/voice/sessions", json={})
    tenant_b_writer.post("/v1/multimodal/voice/sessions", json={})

    response = admin_client.get("/v1/multimodal/voice/sessions")

    assert response.status_code == 200
    assert {item["tenant_id"] for item in response.json()} == {"tenant-a", "tenant-b"}


def test_voice_session_routes_reject_authenticated_user_without_tenant_context(
    writer_client: TestClient,
) -> None:
    tenantless_client = _client(["multimodal:read", "multimodal:write"], tenant_id="")
    create_response = writer_client.post("/v1/multimodal/voice/sessions", json={})
    session_id = create_response.json()["id"]

    start_response = tenantless_client.post("/v1/multimodal/voice/sessions", json={})
    list_response = tenantless_client.get("/v1/multimodal/voice/sessions")
    detail_response = tenantless_client.get(f"/v1/multimodal/voice/sessions/{session_id}")
    health_response = tenantless_client.get(f"/v1/multimodal/voice/sessions/{session_id}/health")
    stop_response = tenantless_client.post(f"/v1/multimodal/voice/sessions/{session_id}/stop")

    assert start_response.status_code == 403
    assert start_response.json()["detail"] == "Tenant context required for authenticated principal"
    assert list_response.status_code == 403
    assert list_response.json()["detail"] == "Tenant context required for authenticated principal"
    assert detail_response.status_code == 403
    assert (
        detail_response.json()["detail"] == "Tenant context required for authenticated principal"
    )
    assert health_response.status_code == 403
    assert (
        health_response.json()["detail"] == "Tenant context required for authenticated principal"
    )
    assert stop_response.status_code == 403
    assert stop_response.json()["detail"] == "Tenant context required for authenticated principal"


def test_voice_session_sanitizes_room_name_components() -> None:
    unsafe_tenant_client = _client(
        ["multimodal:read", "multimodal:write"],
        tenant_id="Tenant / Blue",
    )
    response = unsafe_tenant_client.post(
        "/v1/multimodal/voice/sessions",
        json={"room_name": "Launch Room!!!"},
    )

    assert response.status_code == 201
    room_name = response.json()["room_name"]
    assert room_name.startswith("agent33-voice-tenant-blue-launch-room-")
    assert "!" not in room_name
    assert "/" not in room_name


def test_voice_session_health_and_stop_flow(writer_client: TestClient) -> None:
    create_response = writer_client.post("/v1/multimodal/voice/sessions", json={})
    session_id = create_response.json()["id"]

    health_response = writer_client.get(f"/v1/multimodal/voice/sessions/{session_id}/health")
    stop_response = writer_client.post(f"/v1/multimodal/voice/sessions/{session_id}/stop")

    assert health_response.status_code == 200
    assert health_response.json()["healthy"] is True
    assert stop_response.status_code == 200
    assert stop_response.json()["state"] == "stopped"


@pytest.mark.asyncio
async def test_voice_session_uses_real_sidecar_service_and_persists_artifacts(
    tmp_path: Path,
) -> None:
    voices_path = Path(__file__).resolve().parents[2] / "config" / "voice" / "voices.json"
    sidecar_artifacts_dir = tmp_path / "voice-sidecar-artifacts"
    sidecar_service = VoiceSidecarService(
        voices_path=voices_path,
        artifacts_dir=sidecar_artifacts_dir,
        playback_backend="noop",
    )
    persona_ids = {persona.id for persona in sidecar_service.list_personas()}
    assert {"default", "operator"}.issubset(persona_ids)
    sidecar_app = create_voice_sidecar_app(sidecar_service)
    sidecar_transport = httpx.ASGITransport(app=sidecar_app)
    sidecar_client = VoiceSidecarClient(
        "http://testserver",
        transport=sidecar_transport,
    )

    def daemon_factory(**kwargs: object) -> SidecarVoiceDaemon:
        return SidecarVoiceDaemon(client=sidecar_client, **kwargs)

    _service.configure_voice_runtime(
        enabled=True,
        transport="sidecar",
        url="http://testserver",
        api_key="",
        api_secret="",
        room_prefix="agent33-voice",
        max_sessions=25,
        daemon_factory=daemon_factory,
    )

    transport = httpx.ASGITransport(app=app)
    token = create_access_token(
        "multimodal-user",
        scopes=["multimodal:read", "multimodal:write"],
        tenant_id="tenant-a",
    )
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=headers,
    ) as client:
        created = await client.post("/v1/multimodal/voice/sessions", json={})
        assert created.status_code == 201
        created_payload = created.json()
        assert created_payload["state"] == "active"
        assert created_payload["transport"] == "sidecar"
        assert created_payload["daemon_health"] is True

        session_id = created_payload["id"]
        health_response = await client.get(f"/v1/multimodal/voice/sessions/{session_id}/health")
        assert health_response.status_code == 200
        health_payload = health_response.json()
        assert health_payload["healthy"] is True
        assert health_payload["details"]["health"]["status"] == "ok"
        assert health_payload["details"]["health"]["persona_count"] >= 2
        resolved_voices_path = Path(health_payload["details"]["health"]["voices_path"])
        assert resolved_voices_path.parts[-3:] == ("config", "voice", "voices.json")
        sidecar_session_id = health_payload["details"]["sidecar_session_id"]
        assert sidecar_session_id

        session_dir = sidecar_artifacts_dir / sidecar_session_id
        manifest_path = session_dir / "session.json"
        events_path = session_dir / "events.jsonl"
        assert manifest_path.is_file()
        assert events_path.is_file()

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["state"] == "active"
        assert manifest["room_name"] == created_payload["room_name"]
        assert manifest["persona_id"] == "default"
        events_text = events_path.read_text(encoding="utf-8")
        assert "session.started" in events_text

        stopped = await client.post(f"/v1/multimodal/voice/sessions/{session_id}/stop")
        assert stopped.status_code == 200
        assert stopped.json()["state"] == "stopped"

        stopped_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert stopped_manifest["state"] == "stopped"
        assert stopped_manifest["stopped_at"] is not None
        assert "session.stopped" in events_path.read_text(encoding="utf-8")


def test_voice_session_reads_do_not_mutate_stored_updated_at(writer_client: TestClient) -> None:
    create_response = writer_client.post("/v1/multimodal/voice/sessions", json={})
    session_id = create_response.json()["id"]
    original_updated_at = _service._voice_sessions[session_id].updated_at

    detail_response = writer_client.get(f"/v1/multimodal/voice/sessions/{session_id}")
    health_response = writer_client.get(f"/v1/multimodal/voice/sessions/{session_id}/health")

    assert detail_response.status_code == 200
    assert health_response.status_code == 200
    assert _service._voice_sessions[session_id].updated_at == original_updated_at


def test_voice_session_enforces_concurrency_policy(writer_client: TestClient) -> None:
    writer_client.post(
        "/v1/multimodal/tenants/tenant-a/policy",
        json={"max_voice_concurrent_sessions": 1},
    )

    first = writer_client.post("/v1/multimodal/voice/sessions", json={})
    second = writer_client.post("/v1/multimodal/voice/sessions", json={})

    assert first.status_code == 201
    assert second.status_code == 400
    assert "voice session limit exceeded" in second.json()["detail"]


def test_voice_session_route_returns_503_when_runtime_disabled(writer_client: TestClient) -> None:
    _service.configure_voice_runtime(
        enabled=False,
        transport="stub",
        url="",
        api_key="",
        api_secret="",
        room_prefix="agent33-voice",
        max_sessions=25,
    )

    response = writer_client.post("/v1/multimodal/voice/sessions", json={})

    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


def test_voice_session_route_rejects_direct_livekit_transport(writer_client: TestClient) -> None:
    _service.configure_voice_runtime(
        enabled=True,
        transport="livekit",
        url="wss://livekit.example.com",
        api_key="livekit-key",
        api_secret="livekit-secret",
        room_prefix="agent33-voice",
        max_sessions=25,
    )

    response = writer_client.post("/v1/multimodal/voice/sessions", json={})

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "livekit transport is available via the voice sidecar (S32); "
        "set voice_livekit_enabled=True and configure voice_livekit_api_key, "
        "voice_livekit_api_secret, voice_livekit_ws_url to enable it"
    )
    assert _service._voice_sessions == {}


def test_voice_session_route_redacts_runtime_start_errors(writer_client: TestClient) -> None:
    class _FailingVoiceDaemon:
        def __init__(self, **_: object) -> None:
            pass

        async def start(self) -> None:
            raise RuntimeError("raw secret failure from provider")

        async def stop(self) -> None:
            return None

        def health_check(self) -> bool:
            return False

        def snapshot(self) -> dict[str, object]:
            return {}

    _service.configure_voice_runtime(
        enabled=True,
        transport="stub",
        url="",
        api_key="",
        api_secret="",
        room_prefix="agent33-voice",
        max_sessions=25,
        daemon_factory=_FailingVoiceDaemon,
    )

    response = writer_client.post("/v1/multimodal/voice/sessions", json={})

    assert response.status_code == 503
    assert response.json()["detail"] == "voice runtime could not start session"
    failed_session = next(iter(_service._voice_sessions.values()))
    assert failed_session.state == VoiceSessionState.FAILED
    assert failed_session.last_error == "voice runtime could not start session"


def test_voice_session_detail_is_tenant_scoped(
    writer_client: TestClient, tenant_b_writer: TestClient
) -> None:
    create_response = writer_client.post("/v1/multimodal/voice/sessions", json={})
    session_id = create_response.json()["id"]

    allowed = writer_client.get(f"/v1/multimodal/voice/sessions/{session_id}")
    denied = tenant_b_writer.get(f"/v1/multimodal/voice/sessions/{session_id}")

    assert allowed.status_code == 200
    assert allowed.json()["state"] == VoiceSessionState.ACTIVE
    assert denied.status_code == 404
