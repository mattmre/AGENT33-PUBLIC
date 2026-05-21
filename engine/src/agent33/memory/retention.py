"""Session retention, TTL, and redaction management."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.memory.session import SessionManager


@dataclass
class _TTLEntry:
    session_id: str
    expires_at: float


class RetentionManager:
    """Manages TTL-based expiry and field redaction for sessions."""

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager
        self._ttls: dict[str, float] = {}

    def set_ttl(self, session_id: str, ttl_seconds: int) -> None:
        """Mark a session to expire after *ttl_seconds* from now."""
        self._ttls[session_id] = time.time() + ttl_seconds

    def cleanup(self) -> list[str]:
        """Delete all expired sessions. Returns list of removed session ids."""
        now = time.time()
        expired = [sid for sid, exp in self._ttls.items() if now >= exp]
        for sid in expired:
            with contextlib.suppress(KeyError):
                self._sm.delete(sid)
            del self._ttls[sid]
        return expired

    def redact(self, session_id: str, fields: list[str]) -> None:
        """Replace specified field values with '[REDACTED]' in a session."""
        session = self._sm.get(session_id)
        redacted: dict[str, Any] = {}
        for f in fields:
            if f in session.data:
                redacted[f] = "[REDACTED]"
        if redacted:
            self._sm.update(session_id, redacted)
