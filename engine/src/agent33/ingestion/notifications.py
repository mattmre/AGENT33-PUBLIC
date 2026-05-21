"""Notification hook infrastructure for operator-relevant ingestion events."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import httpx
import structlog
from pydantic import BaseModel

if TYPE_CHECKING:
    from agent33.ingestion.models import CandidateAsset

logger = structlog.get_logger()

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS ingestion_notification_hooks (
    id                   TEXT PRIMARY KEY,
    tenant_id            TEXT NOT NULL,
    name                 TEXT NOT NULL,
    target_url           TEXT NOT NULL,
    event_types          TEXT NOT NULL,
    signing_secret       TEXT,
    enabled              INTEGER NOT NULL DEFAULT 1,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    last_delivery_at     TEXT,
    last_delivery_status TEXT,
    last_response_code   INTEGER,
    last_error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_ingestion_notification_hooks_tenant
    ON ingestion_notification_hooks(tenant_id, enabled);
"""


class IngestionNotificationEvent(StrEnum):
    """Webhook event types emitted by the ingestion subsystem."""

    REVIEW_REQUIRED = "review_required"
    QUARANTINED = "quarantined"
    APPROVED = "approved"
    REJECTED = "rejected"


class NotificationDeliveryStatus(StrEnum):
    """Result of sending a notification payload to a configured hook."""

    DELIVERED = "delivered"
    FAILED = "failed"


class NotificationHookRecord(BaseModel):
    """Stored notification hook definition with delivery health fields."""

    id: str
    tenant_id: str
    name: str
    target_url: str
    event_types: list[IngestionNotificationEvent]
    signing_secret: str | None = None
    enabled: bool = True
    created_at: datetime
    updated_at: datetime
    last_delivery_at: datetime | None = None
    last_delivery_status: NotificationDeliveryStatus | None = None
    last_response_code: int | None = None
    last_error: str | None = None


class NotificationHookView(BaseModel):
    """Public notification hook shape returned by the API."""

    id: str
    tenant_id: str
    name: str
    target_url: str
    event_types: list[IngestionNotificationEvent]
    enabled: bool = True
    created_at: datetime
    updated_at: datetime
    last_delivery_at: datetime | None = None
    last_delivery_status: NotificationDeliveryStatus | None = None
    last_response_code: int | None = None
    last_error: str | None = None


class NotificationDispatchResult(BaseModel):
    """Result of one hook delivery attempt."""

    hook_id: str
    event_type: IngestionNotificationEvent
    delivery_status: NotificationDeliveryStatus
    delivered_at: datetime
    status_code: int | None = None
    error_message: str | None = None


class NotificationTransport(Protocol):
    """Minimal transport contract for sending webhook payloads."""

    def send(
        self,
        *,
        url: str,
        body: str,
        headers: dict[str, str],
        timeout_seconds: float,
        hook_id: str,
        event_type: IngestionNotificationEvent,
    ) -> NotificationDispatchResult: ...


class HttpxNotificationTransport:
    """HTTP transport that delivers notifications via ``httpx``."""

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
        delivered_at = datetime.now(UTC)
        try:
            response = httpx.post(
                url,
                content=body,
                headers=headers,
                timeout=timeout_seconds,
            )
        except httpx.HTTPError as exc:
            return NotificationDispatchResult(
                hook_id=hook_id,
                event_type=event_type,
                delivery_status=NotificationDeliveryStatus.FAILED,
                delivered_at=delivered_at,
                error_message=str(exc),
            )

        if 200 <= response.status_code < 300:
            status = NotificationDeliveryStatus.DELIVERED
            error_message = None
        else:
            status = NotificationDeliveryStatus.FAILED
            error_message = response.text[:500] or f"HTTP {response.status_code}"

        return NotificationDispatchResult(
            hook_id=hook_id,
            event_type=event_type,
            delivery_status=status,
            delivered_at=delivered_at,
            status_code=response.status_code,
            error_message=error_message,
        )


class NotificationHookStore:
    """SQLite-backed storage for ingestion notification hooks."""

    def __init__(self, db_path: str | Path) -> None:
        path_text = str(db_path)
        if path_text != ":memory:":
            Path(path_text).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path_text, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout = 5000")
        if path_text != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def create(
        self,
        *,
        tenant_id: str,
        name: str,
        target_url: str,
        event_types: list[IngestionNotificationEvent],
        signing_secret: str | None,
        enabled: bool,
    ) -> NotificationHookRecord:
        now = datetime.now(UTC)
        record = NotificationHookRecord(
            id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            name=name,
            target_url=target_url,
            event_types=event_types,
            signing_secret=signing_secret,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        self._conn.execute(
            """
            INSERT INTO ingestion_notification_hooks (
                id, tenant_id, name, target_url, event_types, signing_secret,
                enabled, created_at, updated_at, last_delivery_at,
                last_delivery_status, last_response_code, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            self._record_to_row(record),
        )
        self._conn.commit()
        return record

    def list_by_tenant(self, tenant_id: str) -> list[NotificationHookRecord]:
        cursor = self._conn.execute(
            """
            SELECT * FROM ingestion_notification_hooks
            WHERE tenant_id = ?
            ORDER BY created_at ASC
            """,
            (tenant_id,),
        )
        return [self._row_to_record(row) for row in cursor.fetchall()]

    def get(
        self,
        hook_id: str,
        *,
        tenant_id: str | None = None,
    ) -> NotificationHookRecord | None:
        if tenant_id is None:
            cursor = self._conn.execute(
                "SELECT * FROM ingestion_notification_hooks WHERE id = ?",
                (hook_id,),
            )
        else:
            cursor = self._conn.execute(
                """
                SELECT * FROM ingestion_notification_hooks
                WHERE id = ? AND tenant_id = ?
                """,
                (hook_id, tenant_id),
            )
        row = cursor.fetchone()
        return self._row_to_record(row) if row is not None else None

    def update(
        self,
        hook_id: str,
        *,
        tenant_id: str | None = None,
        name: str | None = None,
        target_url: str | None = None,
        event_types: list[IngestionNotificationEvent] | None = None,
        enabled: bool | None = None,
        signing_secret: str | None = None,
        replace_signing_secret: bool = False,
    ) -> NotificationHookRecord | None:
        record = self.get(hook_id, tenant_id=tenant_id)
        if record is None:
            return None

        updated = record.model_copy(
            update={
                "name": name if name is not None else record.name,
                "target_url": target_url if target_url is not None else record.target_url,
                "event_types": event_types if event_types is not None else record.event_types,
                "enabled": enabled if enabled is not None else record.enabled,
                "signing_secret": (
                    signing_secret if replace_signing_secret else record.signing_secret
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        self._conn.execute(
            """
            UPDATE ingestion_notification_hooks
            SET name = ?, target_url = ?, event_types = ?, signing_secret = ?,
                enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                updated.name,
                updated.target_url,
                json.dumps([event.value for event in updated.event_types]),
                updated.signing_secret,
                1 if updated.enabled else 0,
                updated.updated_at.isoformat(),
                hook_id,
            ),
        )
        self._conn.commit()
        return updated

    def record_delivery(self, hook_id: str, result: NotificationDispatchResult) -> None:
        self._conn.execute(
            """
            UPDATE ingestion_notification_hooks
            SET last_delivery_at = ?, last_delivery_status = ?,
                last_response_code = ?, last_error = ?
            WHERE id = ?
            """,
            (
                result.delivered_at.isoformat(),
                result.delivery_status.value,
                result.status_code,
                result.error_message,
                hook_id,
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _record_to_row(record: NotificationHookRecord) -> tuple[Any, ...]:
        return (
            record.id,
            record.tenant_id,
            record.name,
            record.target_url,
            json.dumps([event.value for event in record.event_types]),
            record.signing_secret,
            1 if record.enabled else 0,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            record.last_delivery_at.isoformat() if record.last_delivery_at else None,
            record.last_delivery_status.value if record.last_delivery_status else None,
            record.last_response_code,
            record.last_error,
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> NotificationHookRecord:
        event_types = [
            IngestionNotificationEvent(value) for value in json.loads(row["event_types"])
        ]
        return NotificationHookRecord(
            id=row["id"],
            tenant_id=row["tenant_id"],
            name=row["name"],
            target_url=row["target_url"],
            event_types=event_types,
            signing_secret=row["signing_secret"],
            enabled=bool(row["enabled"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            last_delivery_at=(
                datetime.fromisoformat(row["last_delivery_at"])
                if row["last_delivery_at"] is not None
                else None
            ),
            last_delivery_status=(
                NotificationDeliveryStatus(row["last_delivery_status"])
                if row["last_delivery_status"] is not None
                else None
            ),
            last_response_code=row["last_response_code"],
            last_error=row["last_error"],
        )


class IngestionNotificationService:
    """Manages notification hooks and emits webhook-style event payloads."""

    def __init__(
        self,
        store: NotificationHookStore,
        *,
        transport: NotificationTransport | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self._store = store
        self._transport = transport or HttpxNotificationTransport()
        self._timeout_seconds = timeout_seconds

    def create_hook(
        self,
        *,
        tenant_id: str,
        name: str,
        target_url: str,
        event_types: list[IngestionNotificationEvent],
        signing_secret: str | None = None,
        enabled: bool = True,
    ) -> NotificationHookView:
        record = self._store.create(
            tenant_id=tenant_id,
            name=name,
            target_url=target_url,
            event_types=event_types,
            signing_secret=signing_secret,
            enabled=enabled,
        )
        logger.info(
            "ingestion_notification_hook_created",
            hook_id=record.id,
            tenant_id=tenant_id,
            event_types=[event.value for event in event_types],
        )
        return self._to_view(record)

    def list_hooks(self, tenant_id: str) -> list[NotificationHookView]:
        return [self._to_view(record) for record in self._store.list_by_tenant(tenant_id)]

    def update_hook(
        self,
        hook_id: str,
        *,
        tenant_id: str,
        name: str | None = None,
        target_url: str | None = None,
        event_types: list[IngestionNotificationEvent] | None = None,
        enabled: bool | None = None,
        signing_secret: str | None = None,
        replace_signing_secret: bool = False,
    ) -> NotificationHookView | None:
        record = self._store.update(
            hook_id,
            tenant_id=tenant_id,
            name=name,
            target_url=target_url,
            event_types=event_types,
            enabled=enabled,
            signing_secret=signing_secret,
            replace_signing_secret=replace_signing_secret,
        )
        if record is None:
            return None
        logger.info(
            "ingestion_notification_hook_updated",
            hook_id=hook_id,
            tenant_id=tenant_id,
        )
        return self._to_view(record)

    def emit(
        self,
        asset: CandidateAsset,
        *,
        event_type: IngestionNotificationEvent,
        operator: str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> list[NotificationDispatchResult]:
        matching_hooks = [
            hook
            for hook in self._store.list_by_tenant(asset.tenant_id)
            if hook.enabled and event_type in hook.event_types
        ]
        if not matching_hooks:
            return []

        payload = {
            "event_type": event_type.value,
            "occurred_at": datetime.now(UTC).isoformat(),
            "operator": operator,
            "reason": reason,
            "asset_history_path": f"/v1/ingestion/candidates/{asset.id}/history",
            "asset": asset.model_dump(mode="json"),
            "details": details or {},
        }

        results: list[NotificationDispatchResult] = []
        for hook in matching_hooks:
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
            headers = {
                "Content-Type": "application/json",
                "X-Agent33-Event-Type": event_type.value,
                "X-Agent33-Hook-Id": hook.id,
            }
            if hook.signing_secret:
                digest = hmac.new(
                    hook.signing_secret.encode("utf-8"),
                    body.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()
                headers["X-Agent33-Signature"] = f"sha256={digest}"

            result = self._transport.send(
                url=hook.target_url,
                body=body,
                headers=headers,
                timeout_seconds=self._timeout_seconds,
                hook_id=hook.id,
                event_type=event_type,
            )
            self._store.record_delivery(hook.id, result)
            results.append(result)
            logger.info(
                "ingestion_notification_sent",
                hook_id=hook.id,
                asset_id=asset.id,
                event_type=event_type.value,
                delivery_status=result.delivery_status.value,
                status_code=result.status_code,
            )
        return results

    def close(self) -> None:
        self._store.close()

    @staticmethod
    def _to_view(record: NotificationHookRecord) -> NotificationHookView:
        return NotificationHookView(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            target_url=record.target_url,
            event_types=record.event_types,
            enabled=record.enabled,
            created_at=record.created_at,
            updated_at=record.updated_at,
            last_delivery_at=record.last_delivery_at,
            last_delivery_status=record.last_delivery_status,
            last_response_code=record.last_response_code,
            last_error=record.last_error,
        )
