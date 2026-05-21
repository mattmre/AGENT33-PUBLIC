"""Standalone session catalog with in-memory backend (Track 8).

Provides a self-contained CRUD catalog for session metadata independent of
the OperatorSessionService.  Tracks message/token counts, tags, metadata,
and parent-child lineage for delegation trees.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore

logger = logging.getLogger(__name__)

_NAMESPACE = "memory_session_catalog"


# ---------------------------------------------------------------------------
# Enums and models
# ---------------------------------------------------------------------------


class SessionStatus(StrEnum):
    """Lifecycle status of a catalog session."""

    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"
    ARCHIVED = "archived"


class SessionCatalogEntry(BaseModel):
    """Enriched session metadata stored in the catalog."""

    session_id: str
    agent_id: str = ""
    tenant_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: SessionStatus = SessionStatus.ACTIVE
    message_count: int = 0
    token_count: int = 0
    parent_session_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# Rebuild so PEP 563 deferred annotations resolve at runtime
SessionCatalogEntry.model_rebuild()


class LineageNode(BaseModel):
    """A node in the session delegation tree."""

    session_id: str
    agent_id: str = ""
    status: str = ""
    children: list[LineageNode] = Field(default_factory=list)


LineageNode.model_rebuild()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SessionCatalog:
    """In-memory session catalog with CRUD and lineage tree construction.

    This catalog is self-contained and does **not** depend on
    ``OperatorSessionService``.  It can be upgraded to a database backend
    later by swapping the internal ``_store`` dict with a repository.
    """

    def __init__(
        self,
        state_store: OrchestrationStateStore | None = None,
    ) -> None:
        self._store: dict[str, SessionCatalogEntry] = {}
        self._state_store = state_store
        if state_store is None:
            logger.warning(
                "session_catalog_no_state_store: sessions will not persist across restarts"
            )
        self._load_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            _NAMESPACE,
            {"sessions": [e.model_dump(mode="json") for e in self._store.values()]},
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(_NAMESPACE)
        for item in payload.get("sessions", []):
            if not isinstance(item, dict):
                continue
            try:
                entry = SessionCatalogEntry.model_validate(item)
                self._store[entry.session_id] = entry
            except Exception as exc:
                logger.warning("session_catalog_restore_failed: %s", exc)

    # -- CRUD ---------------------------------------------------------------

    def create_session(
        self,
        *,
        agent_id: str = "",
        tenant_id: str = "",
        parent_session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SessionCatalogEntry:
        """Create and store a new catalog entry. Returns the entry."""
        session_id = uuid.uuid4().hex
        now = datetime.now(UTC)
        entry = SessionCatalogEntry(
            session_id=session_id,
            agent_id=agent_id,
            tenant_id=tenant_id,
            created_at=now,
            updated_at=now,
            status=SessionStatus.ACTIVE,
            parent_session_id=parent_session_id,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._store[session_id] = entry
        logger.debug("session_catalog_created session_id=%s agent_id=%s", session_id, agent_id)
        self._persist_state()
        return entry

    def get_session(self, session_id: str) -> SessionCatalogEntry:
        """Retrieve a session by id.

        Raises:
            KeyError: If the session does not exist.
        """
        entry = self._store.get(session_id)
        if entry is None:
            raise KeyError(f"Session '{session_id}' not found in catalog")
        return entry

    def update_session(
        self,
        session_id: str,
        *,
        status: SessionStatus | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        message_count: int | None = None,
        token_count: int | None = None,
    ) -> SessionCatalogEntry:
        """Update mutable fields on an existing session.

        Only provided (non-None) fields are changed.  ``updated_at`` is
        always refreshed.

        Raises:
            KeyError: If the session does not exist.
        """
        entry = self.get_session(session_id)
        if status is not None:
            entry.status = status
        if tags is not None:
            entry.tags = tags
        if metadata is not None:
            entry.metadata = metadata
        if message_count is not None:
            entry.message_count = message_count
        if token_count is not None:
            entry.token_count = token_count
        entry.updated_at = datetime.now(UTC)
        self._persist_state()
        return entry

    def archive_session(self, session_id: str) -> SessionCatalogEntry:
        """Transition a session to ARCHIVED status.

        Raises:
            KeyError: If the session does not exist.
            ValueError: If the session is already archived.
        """
        entry = self.get_session(session_id)
        if entry.status == SessionStatus.ARCHIVED:
            raise ValueError(f"Session '{session_id}' is already archived")
        entry.status = SessionStatus.ARCHIVED
        entry.updated_at = datetime.now(UTC)
        self._persist_state()
        return entry

    def list_sessions(
        self,
        *,
        status: SessionStatus | None = None,
        agent_id: str | None = None,
        tenant_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[SessionCatalogEntry], int]:
        """List sessions with optional filters.

        Returns ``(page, total)`` where *page* is the slice after
        offset/limit and *total* is the full count of matching entries.
        """
        entries = list(self._store.values())

        if status is not None:
            entries = [e for e in entries if e.status == status]
        if agent_id is not None:
            entries = [e for e in entries if e.agent_id == agent_id]
        if tenant_id is not None:
            entries = [e for e in entries if e.tenant_id == tenant_id]
        if date_from is not None:
            entries = [e for e in entries if e.created_at >= date_from]
        if date_to is not None:
            entries = [e for e in entries if e.created_at <= date_to]

        # Sort newest first
        entries.sort(key=lambda e: e.created_at, reverse=True)

        total = len(entries)
        page = entries[offset : offset + limit]
        return page, total

    # -- Lineage tree -------------------------------------------------------

    def get_lineage_tree(self, session_id: str) -> LineageNode:
        """Build the full delegation tree rooted at or containing *session_id*.

        Walks up the parent chain to find the root, then builds the tree
        downward recursively.  Works for multi-level delegation (grandchild
        agents).

        Raises:
            KeyError: If the session does not exist.
        """
        # Verify the entry exists
        entry = self.get_session(session_id)

        # Walk up to the root, guarding against cycles
        root = entry
        visited: set[str] = {entry.session_id}
        while root.parent_session_id:
            if root.parent_session_id in visited:
                break  # cycle guard
            parent = self._store.get(root.parent_session_id)
            if parent is None:
                break  # orphaned parent reference
            visited.add(parent.session_id)
            root = parent

        # Index children by parent_session_id
        children_map: dict[str, list[SessionCatalogEntry]] = {}
        for e in self._store.values():
            if e.parent_session_id:
                children_map.setdefault(e.parent_session_id, []).append(e)

        def _build(node_entry: SessionCatalogEntry, seen: set[str]) -> LineageNode:
            node = LineageNode(
                session_id=node_entry.session_id,
                agent_id=node_entry.agent_id,
                status=node_entry.status.value,
            )
            for child in children_map.get(node_entry.session_id, []):
                if child.session_id not in seen:
                    seen.add(child.session_id)
                    node.children.append(_build(child, seen))
            return node

        seen: set[str] = {root.session_id}
        return _build(root, seen)
