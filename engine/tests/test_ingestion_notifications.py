"""Focused tests for ingestion notification hooks and asset history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent33.api.routes import ingestion as ingestion_mod
from agent33.ingestion.intake import IntakePipeline
from agent33.ingestion.journal import TransitionJournal
from agent33.ingestion.notifications import (
    IngestionNotificationEvent,
    IngestionNotificationService,
    NotificationDeliveryStatus,
    NotificationDispatchResult,
    NotificationHookStore,
)
from agent33.ingestion.service import IngestionService
from agent33.main import app
from agent33.security.auth import create_access_token

_TENANT = "tenant-ingestion-notifications"


class RecordingTransport:
    """Test transport that captures outbound webhook payloads."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def send(
        self,
        *,
        url: str,
        body: str,
        headers: dict[str, str],
        timeout_seconds: float,
        hook_id: str,
        event_type: IngestionNotificationEvent,
    ) -> NotificationDispatchResult:
        self.requests.append(
            {
                "url": url,
                "body": body,
                "headers": headers,
                "timeout_seconds": timeout_seconds,
                "hook_id": hook_id,
                "event_type": event_type.value,
            }
        )
        return NotificationDispatchResult(
            hook_id=hook_id,
            event_type=event_type,
            delivery_status=NotificationDeliveryStatus.DELIVERED,
            delivered_at=datetime.now(UTC),
            status_code=204,
        )


def _client(scopes: list[str], *, tenant_id: str = _TENANT) -> TestClient:
    token = create_access_token("ingestion-notify-user", scopes=scopes, tenant_id=tenant_id)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def isolated_ingestion_state(tmp_path):
    journal = TransitionJournal(tmp_path / "ingestion-journal.db")
    transport = RecordingTransport()
    notification_service = IngestionNotificationService(
        NotificationHookStore(tmp_path / "ingestion-notification-hooks.db"),
        transport=transport,
    )
    service = IngestionService(journal=journal, notifications=notification_service)
    pipeline = IntakePipeline(service)

    saved_service = ingestion_mod._service
    saved_pipeline = ingestion_mod._intake_pipeline
    saved_notifications = ingestion_mod._notification_service

    ingestion_mod._service = service
    ingestion_mod._intake_pipeline = pipeline
    ingestion_mod._notification_service = notification_service

    saved_state: dict[str, object] = {}
    for key in ("ingestion_service", "intake_pipeline", "ingestion_notification_service"):
        if hasattr(app.state, key):
            saved_state[key] = getattr(app.state, key)
            delattr(app.state, key)

    yield {
        "journal": journal,
        "transport": transport,
        "notification_service": notification_service,
        "service": service,
        "pipeline": pipeline,
    }

    ingestion_mod._service = saved_service
    ingestion_mod._intake_pipeline = saved_pipeline
    ingestion_mod._notification_service = saved_notifications

    for key, value in saved_state.items():
        setattr(app.state, key, value)
    for key in ("ingestion_service", "intake_pipeline", "ingestion_notification_service"):
        if key not in saved_state and hasattr(app.state, key):
            delattr(app.state, key)

    journal.close()
    notification_service.close()


def test_low_confidence_intake_emits_review_and_quarantine_notifications(
    isolated_ingestion_state,
) -> None:
    notification_service: IngestionNotificationService = isolated_ingestion_state[
        "notification_service"
    ]
    pipeline: IntakePipeline = isolated_ingestion_state["pipeline"]
    transport: RecordingTransport = isolated_ingestion_state["transport"]

    hook = notification_service.create_hook(
        tenant_id=_TENANT,
        name="review-webhook",
        target_url="https://hooks.example.test/ingestion",
        event_types=[
            IngestionNotificationEvent.REVIEW_REQUIRED,
            IngestionNotificationEvent.QUARANTINED,
        ],
        signing_secret="super-secret",
    )

    asset = pipeline.submit(
        {
            "name": "quarantined-pack",
            "asset_type": "pack",
            "source_uri": "https://example.test/packs/1",
            "confidence": "low",
        },
        source="mailbox",
        tenant_id=_TENANT,
    )

    emitted_event_types = [request["event_type"] for request in transport.requests]
    assert emitted_event_types == ["review_required", "quarantined"]
    assert all(request["hook_id"] == hook.id for request in transport.requests)
    assert all("X-Agent33-Signature" in request["headers"] for request in transport.requests)

    stored_hook = notification_service.list_hooks(_TENANT)[0]
    assert stored_hook.last_delivery_status == NotificationDeliveryStatus.DELIVERED
    assert stored_hook.last_response_code == 204
    assert asset.metadata["review_required"] is True
    assert asset.metadata["quarantine"] is True


def test_approve_and_reject_emit_operator_notifications(isolated_ingestion_state) -> None:
    notification_service: IngestionNotificationService = isolated_ingestion_state[
        "notification_service"
    ]
    service: IngestionService = isolated_ingestion_state["service"]
    transport: RecordingTransport = isolated_ingestion_state["transport"]

    notification_service.create_hook(
        tenant_id=_TENANT,
        name="decision-webhook",
        target_url="https://hooks.example.test/decisions",
        event_types=[
            IngestionNotificationEvent.APPROVED,
            IngestionNotificationEvent.REJECTED,
        ],
    )

    approved_asset = service.ingest(
        name="approve-me",
        asset_type="skill",
        source_uri="https://example.test/approve",
        tenant_id=_TENANT,
    )
    service.patch_metadata(approved_asset.id, {"review_required": True})
    service.approve(approved_asset.id, operator="op-alice", reason="Safe to validate")

    rejected_asset = service.ingest(
        name="reject-me",
        asset_type="tool",
        source_uri="https://example.test/reject",
        tenant_id=_TENANT,
    )
    service.patch_metadata(rejected_asset.id, {"review_required": True})
    service.reject(rejected_asset.id, operator="op-bob", reason="Rejected by policy")

    emitted_event_types = [request["event_type"] for request in transport.requests]
    assert "approved" in emitted_event_types
    assert "rejected" in emitted_event_types


def test_history_endpoint_returns_asset_and_timeline(isolated_ingestion_state) -> None:
    service: IngestionService = isolated_ingestion_state["service"]
    pipeline: IntakePipeline = isolated_ingestion_state["pipeline"]
    writer_client = _client(["ingestion:read", "ingestion:write"])

    asset = pipeline.submit(
        {
            "name": "history-pack",
            "asset_type": "pack",
            "source_uri": "https://example.test/history",
            "confidence": "low",
        },
        source="mailbox",
        tenant_id=_TENANT,
    )
    service.approve(asset.id, operator="op-historian", reason="Validated after review")

    response = writer_client.get(f"/v1/ingestion/candidates/{asset.id}/history")
    assert response.status_code == 200
    payload = response.json()
    assert payload["asset"]["id"] == asset.id
    assert payload["asset"]["status"] == "validated"
    event_types = [entry["event_type"] for entry in payload["history"]]
    assert event_types == [
        "ingested",
        "review_required",
        "quarantined",
        "transition",
        "approved",
    ]


def test_notification_hook_routes_create_list_and_update(isolated_ingestion_state) -> None:
    writer_client = _client(["ingestion:read", "ingestion:write"])
    reader_client = _client(["ingestion:read"])

    create_response = writer_client.post(
        "/v1/ingestion/notification-hooks",
        json={
            "name": "ops-webhook",
            "target_url": "https://hooks.example.test/operator",
            "event_types": ["review_required", "approved"],
            "signing_secret": "do-not-return",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["name"] == "ops-webhook"
    assert "signing_secret" not in created

    list_response = reader_client.get("/v1/ingestion/notification-hooks")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1

    update_response = writer_client.patch(
        f"/v1/ingestion/notification-hooks/{created['id']}",
        json={"enabled": False, "event_types": ["rejected"]},
    )
    assert update_response.status_code == 200
    assert update_response.json()["enabled"] is False
    assert update_response.json()["event_types"] == ["rejected"]


def test_notification_hook_updates_are_tenant_scoped(isolated_ingestion_state) -> None:
    tenant_a_client = _client(["ingestion:read", "ingestion:write"], tenant_id="tenant-a")
    tenant_b_client = _client(["ingestion:read", "ingestion:write"], tenant_id="tenant-b")

    create_response = tenant_a_client.post(
        "/v1/ingestion/notification-hooks",
        json={
            "name": "tenant-a-hook",
            "target_url": "https://hooks.example.test/tenant-a",
            "event_types": ["review_required"],
        },
    )
    assert create_response.status_code == 201
    hook_id = create_response.json()["id"]

    cross_tenant_update = tenant_b_client.patch(
        f"/v1/ingestion/notification-hooks/{hook_id}",
        json={"enabled": False},
    )
    assert cross_tenant_update.status_code == 404

    list_response = tenant_a_client.get("/v1/ingestion/notification-hooks")
    assert list_response.status_code == 200
    assert list_response.json()[0]["enabled"] is True
