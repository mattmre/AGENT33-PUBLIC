"""Mailbox seam for depositing task-metric events into the ingestion pipeline.

External operators post events here; ``candidate_asset`` events are forwarded
directly to :class:`IntakePipeline`; all other event types are held in an
inbox until drained, using a durable backing store when configured.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from agent33.ingestion.intake import IntakePipeline
    from agent33.ingestion.mailbox_persistence import MailboxInboxPersistence

logger = structlog.get_logger()


class IngestionMailbox:
    """Thin event seam between external operators and the ingestion pipeline.

    Args:
        pipeline: The :class:`IntakePipeline` that receives ``candidate_asset``
            events.  Injected at construction so tests can supply a mock.
        persistence: Optional durable queue backing store for non-candidate
            events. When omitted, the inbox remains in-memory only.
    """

    def __init__(
        self,
        pipeline: IntakePipeline,
        *,
        persistence: MailboxInboxPersistence | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._persistence = persistence
        self._inbox: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def post(self, event: dict[str, Any], *, sender: str, tenant_id: str) -> dict[str, str]:
        """Validate, stamp, and route an incoming event.

        Required keys in *event*:
        - ``event_type``: non-empty ``str``
        - ``payload``: ``dict``

        ``candidate_asset`` events are forwarded to
        :meth:`IntakePipeline.submit` with the sender stored as the intake
        source. Other event types are appended to the tenant inbox and
        persisted when a mailbox backing store is configured.

        Args:
            event: Raw event dict from the caller.
            sender: Identifies the external operator or system posting the event.
            tenant_id: Tenant scope; controls routing and inbox keying.

        Returns:
            ``{"status": "accepted", "event_id": "<uuid4>"}``

        Raises:
            ValueError: If ``event_type`` is missing/empty or ``payload`` is not
                a ``dict``.
        """
        event_type = event.get("event_type")
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("'event_type' must be a non-empty string.")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("'payload' must be a dict.")

        event_id = str(uuid.uuid4())
        stamped: dict[str, Any] = {
            **event,
            "event_id": event_id,
            "received_at": datetime.now(UTC).isoformat(),
            "sender": sender,
            "tenant_id": tenant_id,
        }

        if event_type == "candidate_asset":
            self._pipeline.submit(payload, source=sender, tenant_id=tenant_id)
            logger.info(
                "mailbox_event_routed_to_pipeline",
                event_id=event_id,
                sender=sender,
                tenant_id=tenant_id,
            )
        else:
            if self._persistence is not None:
                self._persistence.enqueue(stamped)
            else:
                self._inbox.setdefault(tenant_id, []).append(stamped)
            logger.info(
                "mailbox_event_queued",
                event_type=event_type,
                event_id=event_id,
                tenant_id=tenant_id,
            )

        return {"status": "accepted", "event_id": event_id}

    def drain(self, tenant_id: str) -> list[dict[str, Any]]:
        """Return and clear all queued events for *tenant_id*.

        Events that were routed to the intake pipeline are not present here.

        Args:
            tenant_id: Tenant whose inbox should be drained.

        Returns:
            List of stamped event dicts, oldest first. Empty list if the inbox
            had no entries for this tenant.
        """
        if self._persistence is not None:
            return self._persistence.drain(tenant_id)
        events = self._inbox.pop(tenant_id, [])
        return events

    def heartbeat(self) -> dict[str, Any]:
        """Return a liveness snapshot for external health checks.

        Returns:
            ``{"status": "ok", "inbox_depth": <int>, "pipeline_healthy": True}``
        """
        if self._persistence is not None:
            depth = self._persistence.depth()
        else:
            depth = sum(len(v) for v in self._inbox.values())
        return {"status": "ok", "inbox_depth": depth, "pipeline_healthy": True}
