"""Session archive service: transition completed sessions to archived state."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from agent33.sessions.models import OperatorSessionStatus

if TYPE_CHECKING:
    from agent33.sessions.models import OperatorSession
    from agent33.sessions.service import OperatorSessionService

logger = logging.getLogger(__name__)


class SessionArchiveService:
    """Archive and clean up completed operator sessions."""

    def __init__(self, session_service: OperatorSessionService) -> None:
        self._session_service = session_service

    async def archive(self, session_id: str) -> OperatorSession:
        """Transition a completed/crashed/suspended session to ARCHIVED status.

        Only sessions that are NOT active can be archived.

        Raises:
            KeyError: If the session is not found.
            ValueError: If the session is in ACTIVE or already ARCHIVED status.
        """
        session = await self._session_service.get_session(session_id)
        if session is None:
            raise KeyError(f"Session {session_id} not found")

        if session.status == OperatorSessionStatus.ACTIVE:
            raise ValueError(
                f"Cannot archive an active session (session_id={session_id}). "
                f"End or suspend the session first."
            )
        if session.status == OperatorSessionStatus.ARCHIVED:
            raise ValueError(f"Session {session_id} is already archived.")

        previous_status = session.status
        session.status = OperatorSessionStatus.ARCHIVED
        session.updated_at = datetime.now(UTC)
        self._session_service.storage.save_session(session)
        self._session_service.clear_terminal_session_state(session_id)

        logger.info(
            "session_archived session_id=%s previous_status=%s",
            session_id,
            previous_status.value,
        )
        return session

    async def cleanup_archived(self, older_than_days: int = 90) -> int:
        """Delete archived sessions older than the specified number of days.

        Returns the number of sessions removed.
        """
        cutoff = datetime.now(UTC)
        removed = 0
        sessions = await self._session_service.list_sessions(
            status=OperatorSessionStatus.ARCHIVED,
            limit=10000,
        )
        for session in sessions:
            age_days = (cutoff - session.updated_at).total_seconds() / 86400
            if age_days >= older_than_days:
                self._session_service.clear_terminal_session_state(session.session_id)
                self._session_service.storage.delete_session(session.session_id)
                removed += 1
                logger.debug(
                    "archived_session_deleted session_id=%s age_days=%.1f",
                    session.session_id,
                    age_days,
                )

        if removed:
            logger.info(
                "archived_sessions_cleaned count=%d older_than_days=%d",
                removed,
                older_than_days,
            )
        return removed
