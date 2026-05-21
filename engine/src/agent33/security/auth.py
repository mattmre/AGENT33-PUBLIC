"""JWT authentication and API key management."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

import jwt
from pydantic import BaseModel

from agent33.config import settings
from agent33.security.auth_repository import (
    InMemoryAuthRepository,
    get_auth_repository,
)

# ---------------------------------------------------------------------------
# Token payload model
# ---------------------------------------------------------------------------


class TokenPayload(BaseModel):
    """Decoded JWT payload."""

    sub: str
    scopes: list[str] = []
    exp: int = 0
    tenant_id: str = ""


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def create_access_token(
    subject: str,
    scopes: list[str] | None = None,
    tenant_id: str = "",
) -> str:
    """Create a signed JWT for *subject* with the given *scopes*."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "scopes": scopes or [],
        "iat": now,
        "exp": now + settings.jwt_expire_minutes * 60,
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def verify_token(token: str) -> TokenPayload:
    """Decode and validate a JWT, returning a :class:`TokenPayload`.

    Raises ``jwt.InvalidTokenError`` on failure.
    """
    data = jwt.decode(
        token,
        settings.jwt_secret.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )
    return TokenPayload(**data)


# ---------------------------------------------------------------------------
# API key management (repository-backed)
# ---------------------------------------------------------------------------


def _get_api_keys_dict() -> dict[str, dict[str, Any]]:
    """Return the underlying API keys dict from the current repository.

    This enables backwards compatibility for tests that directly import and
    manipulate ``_api_keys``.
    """
    repo = get_auth_repository()
    if isinstance(repo, InMemoryAuthRepository):
        return repo._api_keys
    # For non-in-memory repositories, return an empty dict as a fallback.
    # Direct dict manipulation is not supported on non-in-memory backends.
    return {}  # pragma: no cover


# Backwards-compatible module-level reference.
# Tests that import ``_api_keys`` from this module will get the dict from the
# default InMemoryAuthRepository.  If ``set_auth_repository`` is called with a
# new InMemoryAuthRepository, callers that cached this reference will still see
# the old dict.  The public API functions below always go through the repository.
_api_keys: dict[str, dict[str, Any]] = _get_api_keys_dict()


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key(
    subject: str,
    scopes: list[str] | None = None,
    tenant_id: str = "",
    expires_in_seconds: int | None = None,
) -> dict[str, Any]:
    """Generate a new API key and return its metadata including the raw key.

    Returns ``{"key_id": ..., "key": ..., "subject": ..., "scopes": [...], ...}``.
    The raw ``key`` is only available at creation time.

    If *expires_in_seconds* is provided, the key will be rejected after that
    duration.  ``None`` means the key never expires.
    """
    raw_key = f"a33_{secrets.token_urlsafe(32)}"
    key_id = secrets.token_hex(8)
    hashed = _hash_key(raw_key)
    created_at = int(time.time())
    expires_at = (created_at + expires_in_seconds) if expires_in_seconds else 0

    repo = get_auth_repository()
    repo.create_api_key(
        key_hash=hashed,
        key_id=key_id,
        subject=subject,
        scopes=scopes or [],
        tenant_id=tenant_id,
        expires_at=expires_at,
    )

    return {
        "key_id": key_id,
        "key": raw_key,
        "subject": subject,
        "scopes": scopes or [],
        "tenant_id": tenant_id,
        "expires_at": expires_at,
    }


def validate_api_key(key: str) -> TokenPayload | None:
    """Validate an API key and return a :class:`TokenPayload`, or ``None``."""
    hashed = _hash_key(key)
    repo = get_auth_repository()
    entry = repo.get_api_key(hashed)
    if entry is None:
        return None
    # Check expiration
    expires_at = entry.get("expires_at", 0)
    if expires_at and int(time.time()) > expires_at:
        # Key has expired -- remove it and reject
        repo.delete_api_key(hashed)
        return None
    return TokenPayload(
        sub=entry["subject"],
        scopes=entry["scopes"],
        exp=expires_at,
        tenant_id=entry.get("tenant_id", ""),
    )


def revoke_api_key(key_id: str, requesting_subject: str | None = None) -> bool:
    """Revoke an API key by its *key_id*.  Returns ``True`` if found.

    If *requesting_subject* is provided, only allow revocation if the key
    belongs to that subject or if requesting_subject is None (admin bypass).
    """
    repo = get_auth_repository()
    return repo.revoke_api_key_by_id(key_id, requesting_subject=requesting_subject)
