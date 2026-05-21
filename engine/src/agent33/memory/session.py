"""Encrypted session management."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cryptography.fernet import Fernet


@dataclass
class SessionData:
    """Holds session state."""

    session_id: str
    user_id: str
    agent_name: str
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class SessionManager:
    """CRUD for encrypted sessions stored in memory."""

    def __init__(self, encryption_key: str | None = None) -> None:
        if encryption_key:
            # Derive a valid Fernet key from an arbitrary string.
            derived = hashlib.sha256(encryption_key.encode()).digest()
            self._fernet = Fernet(base64.urlsafe_b64encode(derived))
        else:
            self._fernet = Fernet(Fernet.generate_key())
        self._store: dict[str, bytes] = {}

    def _encrypt(self, data: dict[str, Any]) -> bytes:
        return self._fernet.encrypt(json.dumps(data).encode())

    def _decrypt(self, token: bytes) -> dict[str, Any]:
        return json.loads(self._fernet.decrypt(token).decode())  # type: ignore[no-any-return]

    def create(self, user_id: str, agent_name: str) -> str:
        """Create a new session and return its id."""
        session_id = uuid.uuid4().hex
        session = SessionData(
            session_id=session_id,
            user_id=user_id,
            agent_name=agent_name,
        )
        payload = {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "agent_name": session.agent_name,
            "data": session.data,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
        self._store[session_id] = self._encrypt(payload)
        return session_id

    def get(self, session_id: str) -> SessionData:
        """Retrieve a session by id. Raises KeyError if not found."""
        if session_id not in self._store:
            raise KeyError(f"Session {session_id} not found")
        raw = self._decrypt(self._store[session_id])
        return SessionData(**raw)

    def update(self, session_id: str, data: dict[str, Any]) -> None:
        """Merge *data* into the session's data dict."""
        session = self.get(session_id)
        session.data.update(data)
        session.updated_at = datetime.now(UTC).isoformat()
        payload = {
            "session_id": session.session_id,
            "user_id": session.user_id,
            "agent_name": session.agent_name,
            "data": session.data,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }
        self._store[session_id] = self._encrypt(payload)

    def delete(self, session_id: str) -> None:
        """Remove a session. Raises KeyError if not found."""
        if session_id not in self._store:
            raise KeyError(f"Session {session_id} not found")
        del self._store[session_id]

    def exists(self, session_id: str) -> bool:
        """Check whether a session exists."""
        return session_id in self._store
