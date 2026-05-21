"""Session catalog: enriched listing for the operator control plane."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.sessions.models import OperatorSessionStatus
    from agent33.sessions.service import OperatorSessionService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SessionCatalogEntry(BaseModel):
    """Enriched session metadata for the operator catalog."""

    session_id: str
    purpose: str
    status: str
    agent_name: str = ""
    started_at: datetime
    ended_at: datetime | None = None
    event_count: int = 0
    task_count: int = 0
    parent_session_id: str | None = None
    idle_seconds: float = 0.0
    tenant_id: str = ""


# Rebuild Pydantic model so it resolves 'datetime' under PEP 563
SessionCatalogEntry.model_rebuild()


class SessionCatalogResponse(BaseModel):
    """Paginated catalog listing."""

    entries: list[SessionCatalogEntry] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SessionCatalog:
    """Bridge OperatorSessionService into operator control plane with enriched metadata."""

    def __init__(self, session_service: OperatorSessionService) -> None:
        self._session_service = session_service

    async def list_catalog(
        self,
        status: OperatorSessionStatus | None = None,
        agent_name: str | None = None,
        tenant_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SessionCatalogResponse:
        """Return a paginated catalog of enriched session entries.

        Loads all matching sessions from the underlying service, applies
        offset/limit pagination, and computes derived fields like idle_seconds.
        """
        # The underlying storage does not support offset, only limit.
        # Fetch all matching sessions so we can compute a correct total
        # and apply offset/limit pagination in memory.
        raw_sessions = await self._session_service.list_sessions(
            status=status,
            limit=10000,
            tenant_id=tenant_id,
        )

        # Apply agent_name filter if specified
        if agent_name:
            raw_sessions = [
                s for s in raw_sessions if s.context.get("agent_name", "") == agent_name
            ]

        total = len(raw_sessions)
        page = raw_sessions[offset : offset + limit]

        now = datetime.now(UTC)
        entries: list[SessionCatalogEntry] = []
        for session in page:
            idle = (now - session.updated_at).total_seconds()
            entries.append(
                SessionCatalogEntry(
                    session_id=session.session_id,
                    purpose=session.purpose,
                    status=session.status.value,
                    agent_name=session.context.get("agent_name", ""),
                    started_at=session.started_at,
                    ended_at=session.ended_at,
                    event_count=session.event_count,
                    task_count=session.task_count,
                    parent_session_id=session.parent_session_id,
                    idle_seconds=round(idle, 2),
                    tenant_id=session.tenant_id,
                )
            )

        return SessionCatalogResponse(
            entries=entries,
            total=total,
            offset=offset,
            limit=limit,
        )
