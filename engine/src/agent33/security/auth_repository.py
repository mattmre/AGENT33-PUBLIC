"""Repository abstraction for auth users and API keys.

Provides a protocol-based repository pattern that supports both in-memory
and database-backed implementations for multi-replica safety.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AuthRepository(Protocol):
    """Protocol for user and API key storage."""

    def get_user(self, username: str) -> dict[str, Any] | None:
        """Get a user by username."""
        ...

    def create_user(
        self,
        username: str,
        password_hash: str,
        tenant_id: str,
        role: str = "user",
        *,
        salt: str = "",
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new user. Raises ValueError if user already exists."""
        ...

    def set_user(self, username: str, user_data: dict[str, Any]) -> None:
        """Set user data directly (for bootstrap / test compatibility)."""
        ...

    def has_user(self, username: str) -> bool:
        """Check if a user exists."""
        ...

    def delete_user(self, username: str) -> bool:
        """Delete a user. Returns True if found and deleted."""
        ...

    def list_users(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """List users, optionally filtered by tenant."""
        ...

    def get_api_key(self, key_hash: str) -> dict[str, Any] | None:
        """Get API key metadata by hash."""
        ...

    def create_api_key(
        self,
        key_hash: str,
        key_id: str,
        subject: str,
        scopes: list[str],
        tenant_id: str,
        expires_at: int = 0,
    ) -> dict[str, Any]:
        """Store a new API key."""
        ...

    def delete_api_key(self, key_hash: str) -> bool:
        """Delete an API key by hash. Returns True if found and deleted."""
        ...

    def revoke_api_key_by_id(self, key_id: str, requesting_subject: str | None = None) -> bool:
        """Revoke an API key by its key_id.

        If *requesting_subject* is provided, only allow revocation if the key
        belongs to that subject or if requesting_subject is None (admin bypass).
        """
        ...

    def list_api_keys(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        """List API keys, optionally filtered by tenant."""
        ...


class InMemoryAuthRepository:
    """In-memory implementation preserving current behavior.

    Exposes ``_users`` and ``_api_keys`` dicts directly for backwards
    compatibility with existing tests that manipulate them.
    """

    def __init__(self) -> None:
        self._users: dict[str, dict[str, Any]] = {}
        self._api_keys: dict[str, dict[str, Any]] = {}

    def get_user(self, username: str) -> dict[str, Any] | None:
        return self._users.get(username)

    def create_user(
        self,
        username: str,
        password_hash: str,
        tenant_id: str,
        role: str = "user",
        *,
        salt: str = "",
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        if username in self._users:
            raise ValueError(f"User {username} already exists")
        user: dict[str, Any] = {
            "username": username,
            "password_hash": password_hash,
            "tenant_id": tenant_id,
            "role": role,
        }
        if salt:
            user["salt"] = salt
        if scopes is not None:
            user["scopes"] = scopes
        self._users[username] = user
        return user

    def set_user(self, username: str, user_data: dict[str, Any]) -> None:
        self._users[username] = user_data

    def has_user(self, username: str) -> bool:
        return username in self._users

    def delete_user(self, username: str) -> bool:
        return self._users.pop(username, None) is not None

    def list_users(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        users = list(self._users.values())
        if tenant_id is not None:
            users = [user for user in users if user.get("tenant_id") == tenant_id]
        return users

    def get_api_key(self, key_hash: str) -> dict[str, Any] | None:
        return self._api_keys.get(key_hash)

    def create_api_key(
        self,
        key_hash: str,
        key_id: str,
        subject: str,
        scopes: list[str],
        tenant_id: str,
        expires_at: int = 0,
    ) -> dict[str, Any]:
        record = {
            "key_id": key_id,
            "subject": subject,
            "scopes": scopes,
            "tenant_id": tenant_id,
            "created_at": int(time.time()),
            "expires_at": expires_at,
        }
        self._api_keys[key_hash] = record
        return record

    def delete_api_key(self, key_hash: str) -> bool:
        return self._api_keys.pop(key_hash, None) is not None

    def revoke_api_key_by_id(self, key_id: str, requesting_subject: str | None = None) -> bool:
        for h, entry in list(self._api_keys.items()):
            if entry["key_id"] == key_id:
                if requesting_subject is not None and entry["subject"] != requesting_subject:
                    return False  # not owned by requester
                del self._api_keys[h]
                return True
        return False

    def list_api_keys(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        keys = list(self._api_keys.values())
        if tenant_id is not None:
            keys = [k for k in keys if k.get("tenant_id") == tenant_id]
        return keys


class SqliteAuthRepository:
    """SQLite-backed auth repository for durable Phase 23 lifecycle state."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS phase23_auth_users ("
                "  username TEXT PRIMARY KEY,"
                "  tenant_id TEXT NOT NULL,"
                "  data TEXT NOT NULL"
                ")"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_phase23_auth_users_tenant "
                "ON phase23_auth_users(tenant_id)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS phase23_api_keys ("
                "  key_hash TEXT PRIMARY KEY,"
                "  key_id TEXT NOT NULL,"
                "  subject TEXT NOT NULL,"
                "  tenant_id TEXT NOT NULL,"
                "  data TEXT NOT NULL"
                ")"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_phase23_api_keys_key_id "
                "ON phase23_api_keys(key_id)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_phase23_api_keys_tenant "
                "ON phase23_api_keys(tenant_id)"
            )
            self._conn.commit()

    def get_user(self, username: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM phase23_auth_users WHERE username = ?",
                (username,),
            ).fetchone()
        return None if row is None else self._decode_record(row["data"])

    def create_user(
        self,
        username: str,
        password_hash: str,
        tenant_id: str,
        role: str = "user",
        *,
        salt: str = "",
        scopes: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._user_exists(username):
                raise ValueError(f"User {username} already exists")
            user: dict[str, Any] = {
                "username": username,
                "password_hash": password_hash,
                "tenant_id": tenant_id,
                "role": role,
            }
            if salt:
                user["salt"] = salt
            if scopes is not None:
                user["scopes"] = scopes
            self._upsert_user(username, user)
        return dict(user)

    def set_user(self, username: str, user_data: dict[str, Any]) -> None:
        user = dict(user_data)
        user.setdefault("username", username)
        with self._lock:
            self._upsert_user(username, user)

    def has_user(self, username: str) -> bool:
        with self._lock:
            return self._user_exists(username)

    def delete_user(self, username: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM phase23_auth_users WHERE username = ?",
                (username,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def list_users(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if tenant_id is None:
                rows = self._conn.execute(
                    "SELECT data FROM phase23_auth_users ORDER BY username"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT data FROM phase23_auth_users WHERE tenant_id = ? ORDER BY username",
                    (tenant_id,),
                ).fetchall()
        return [self._decode_record(row["data"]) for row in rows]

    def get_api_key(self, key_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM phase23_api_keys WHERE key_hash = ?",
                (key_hash,),
            ).fetchone()
        return None if row is None else self._decode_record(row["data"])

    def create_api_key(
        self,
        key_hash: str,
        key_id: str,
        subject: str,
        scopes: list[str],
        tenant_id: str,
        expires_at: int = 0,
    ) -> dict[str, Any]:
        record = {
            "key_id": key_id,
            "subject": subject,
            "scopes": list(scopes),
            "tenant_id": tenant_id,
            "created_at": int(time.time()),
            "expires_at": expires_at,
        }
        with self._lock:
            self._upsert_api_key(key_hash, record)
        return dict(record)

    def delete_api_key(self, key_hash: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM phase23_api_keys WHERE key_hash = ?",
                (key_hash,),
            )
            self._conn.commit()
            return cursor.rowcount > 0

    def revoke_api_key_by_id(self, key_id: str, requesting_subject: str | None = None) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT key_hash, data FROM phase23_api_keys WHERE key_id = ?",
                (key_id,),
            ).fetchone()
            if row is None:
                return False
            entry = self._decode_record(row["data"])
            if requesting_subject is not None and entry["subject"] != requesting_subject:
                return False
            self._conn.execute(
                "DELETE FROM phase23_api_keys WHERE key_hash = ?",
                (row["key_hash"],),
            )
            self._conn.commit()
            return True

    def list_api_keys(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if tenant_id is None:
                rows = self._conn.execute(
                    "SELECT data FROM phase23_api_keys ORDER BY key_id"
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT data FROM phase23_api_keys WHERE tenant_id = ? ORDER BY key_id",
                    (tenant_id,),
                ).fetchall()
        return [self._decode_record(row["data"]) for row in rows]

    def set_api_key(self, key_hash: str, record: dict[str, Any]) -> None:
        """Store an existing API-key record during repository migration."""
        with self._lock:
            self._upsert_api_key(key_hash, dict(record))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _user_exists(self, username: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM phase23_auth_users WHERE username = ?",
            (username,),
        ).fetchone()
        return row is not None

    def _upsert_user(self, username: str, user: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO phase23_auth_users (username, tenant_id, data) "
            "VALUES (?, ?, ?)",
            (
                username,
                str(user.get("tenant_id", "")),
                json.dumps(user, sort_keys=True),
            ),
        )
        self._conn.commit()

    def _upsert_api_key(self, key_hash: str, record: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO phase23_api_keys "
            "(key_hash, key_id, subject, tenant_id, data) VALUES (?, ?, ?, ?, ?)",
            (
                key_hash,
                str(record["key_id"]),
                str(record["subject"]),
                str(record.get("tenant_id", "")),
                json.dumps(record, sort_keys=True),
            ),
        )
        self._conn.commit()

    @staticmethod
    def _decode_record(raw: str) -> dict[str, Any]:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Invalid auth repository record")
        return dict(data)


# Module-level accessor for the repository singleton
_repository: AuthRepository | None = None


def get_auth_repository() -> AuthRepository:
    """Get the current auth repository. Creates in-memory default if not set."""
    global _repository  # noqa: PLW0603
    if _repository is None:
        _repository = InMemoryAuthRepository()
    return _repository


def set_auth_repository(repo: AuthRepository) -> None:
    """Set the auth repository. Called during app lifespan."""
    global _repository  # noqa: PLW0603
    _repository = repo
