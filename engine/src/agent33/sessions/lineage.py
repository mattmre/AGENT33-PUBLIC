"""Session lineage: parent-child tree reconstruction from session chains."""

from __future__ import annotations

import logging
from datetime import datetime  # noqa: TC003 -- Pydantic needs runtime type
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agent33.sessions.models import OperatorSession
    from agent33.sessions.service import OperatorSessionService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SessionLineageNode(BaseModel):
    """A node in the session lineage tree."""

    session_id: str
    purpose: str
    status: str
    agent_name: str = ""
    parent_session_id: str | None = None
    children: list[SessionLineageNode] = Field(default_factory=list)
    started_at: datetime
    ended_at: datetime | None = None


# Rebuild Pydantic model so recursive type resolves under PEP 563
SessionLineageNode.model_rebuild()


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _session_to_node(session: OperatorSession) -> SessionLineageNode:
    """Convert an OperatorSession to a lineage node (without children)."""
    return SessionLineageNode(
        session_id=session.session_id,
        purpose=session.purpose,
        status=session.status.value,
        agent_name=session.context.get("agent_name", ""),
        parent_session_id=session.parent_session_id,
        started_at=session.started_at,
        ended_at=session.ended_at,
    )


class SessionLineageBuilder:
    """Builds parent-child trees from OperatorSession.parent_session_id chains."""

    def __init__(self, session_service: OperatorSessionService) -> None:
        self._session_service = session_service

    async def build_tree(self, session_id: str) -> SessionLineageNode:
        """Build the lineage tree rooted at the given session.

        Walks up the parent chain to find the root, then builds the
        full tree downward from that root.

        Raises:
            KeyError: If the session is not found.
        """
        session = await self._session_service.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")

        # Walk up to the root
        root = session
        visited: set[str] = {session.session_id}
        while root.parent_session_id:
            if root.parent_session_id in visited:
                # Cycle detected; stop here
                break
            visited.add(root.parent_session_id)
            parent = await self._session_service.get_session(root.parent_session_id)
            if parent is None:
                break
            root = parent

        # Collect all sessions so we can build the tree
        all_sessions = await self._session_service.list_sessions(limit=10000)
        return self._build_subtree(root, all_sessions)

    async def build_forest(self, tenant_id: str | None = None) -> list[SessionLineageNode]:
        """Build lineage trees for all root sessions (those with no parent).

        Returns a list of root nodes, each with their children populated.
        """
        all_sessions = await self._session_service.list_sessions(limit=10000, tenant_id=tenant_id)

        roots = [s for s in all_sessions if not s.parent_session_id]
        return [self._build_subtree(root, all_sessions) for root in roots]

    @staticmethod
    def _build_subtree(
        root: OperatorSession,
        all_sessions: list[OperatorSession],
    ) -> SessionLineageNode:
        """Build a subtree from a root session and all available sessions."""
        # Index children by parent_session_id
        children_map: dict[str, list[OperatorSession]] = {}
        for s in all_sessions:
            if s.parent_session_id:
                children_map.setdefault(s.parent_session_id, []).append(s)

        def _recurse(session: OperatorSession, seen: set[str]) -> SessionLineageNode:
            node = _session_to_node(session)
            child_sessions = children_map.get(session.session_id, [])
            for child in child_sessions:
                if child.session_id in seen:
                    continue
                seen.add(child.session_id)
                node.children.append(_recurse(child, seen))
            return node

        seen: set[str] = {root.session_id}
        return _recurse(root, seen)
