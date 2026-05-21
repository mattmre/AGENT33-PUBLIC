"""Repository abstraction for auth users and API keys.

Provides a protocol-based repository pattern that supports both in-memory
and database-backed implementations for multi-replica safety.
"""

from __future__ import annotations

import time
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
