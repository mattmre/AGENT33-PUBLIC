"""Authentication API routes."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent33.api.route_approvals import require_route_mutation_approval
from agent33.config import settings
from agent33.security.auth import (
    create_access_token,
    generate_api_key,
    revoke_api_key,
)
from agent33.security.auth_repository import (
    InMemoryAuthRepository,
    get_auth_repository,
)
from agent33.security.permissions import _get_token_payload, require_scope

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# User store -- backed by AuthRepository
# ---------------------------------------------------------------------------


def _get_users_dict() -> dict[str, dict[str, Any]]:
    """Return the underlying users dict from the current repository.

    Enables backwards compatibility for tests that directly import and
    manipulate ``_users``.
    """
    repo = get_auth_repository()
    if isinstance(repo, InMemoryAuthRepository):
        return repo._users
    return {}  # pragma: no cover


# Backwards-compatible module-level reference.
# Tests that import ``_users`` will get the dict from the default
# InMemoryAuthRepository.
_users: dict[str, dict[str, Any]] = _get_users_dict()
_LEGACY_PBKDF2_SALT = b"agent33-salt"


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000).hex()


def _get_user_salt(user: dict[str, Any]) -> bytes:
    salt_hex = user.get("salt")
    if isinstance(salt_hex, str):
        try:
            return bytes.fromhex(salt_hex)
        except ValueError as e:
            logger.warning("Auth header parse failed: %s", e)
    # Backward-compatible fallback for legacy in-memory test fixtures.
    return _LEGACY_PBKDF2_SALT


def _parse_scopes(scopes_raw: str, *, ensure_admin: bool = False) -> list[str]:
    scopes = [scope.strip() for scope in scopes_raw.split(",") if scope.strip()]
    if ensure_admin and "admin" not in scopes:
        scopes.insert(0, "admin")
    return scopes


def _bootstrap_default_user() -> None:
    if not settings.auth_bootstrap_enabled:
        return
    username = settings.auth_bootstrap_admin_username.strip()
    password = settings.auth_bootstrap_admin_password.get_secret_value()
    if not username or not password:
        return
    repo = get_auth_repository()
    if repo.has_user(username):
        return
    salt = secrets.token_bytes(16)
    repo.create_user(
        username=username,
        password_hash=_hash_password(password, salt),
        tenant_id="",
        salt=salt.hex(),
        scopes=_parse_scopes(settings.auth_bootstrap_admin_scopes, ensure_admin=True),
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ApiKeyRequest(BaseModel):
    subject: str
    scopes: list[str] = Field(default_factory=list)


class ApiKeyResponse(BaseModel):
    key_id: str
    key: str
    subject: str
    scopes: list[str]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/token", response_model=TokenResponse)
async def login(body: LoginRequest) -> TokenResponse:
    """Authenticate with username/password and receive a JWT."""
    _bootstrap_default_user()
    repo = get_auth_repository()
    user = repo.get_user(body.username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.get("enabled", True) is False:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is disabled")

    password_hash = _hash_password(body.password, _get_user_salt(user))
    if not hmac.compare_digest(password_hash, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(
        subject=body.username,
        scopes=list(user.get("scopes", [])),
        tenant_id=str(user.get("tenant_id", "")),
    )
    return TokenResponse(access_token=token)


@router.post(
    "/api-keys",
    response_model=ApiKeyResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_scope("admin")],
)
async def create_api_key(body: ApiKeyRequest, request: Request) -> ApiKeyResponse:
    """Generate a new API key."""
    require_route_mutation_approval(
        request,
        route_name="auth.api_keys.create",
        operation="create",
        arguments=body.model_dump(mode="json"),
        details="API key creation requires an explicit approval token.",
    )
    result = generate_api_key(subject=body.subject, scopes=body.scopes)
    return ApiKeyResponse(**result)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_api_key(key_id: str, request: Request) -> None:
    """Revoke an API key by its identifier."""
    payload = _get_token_payload(request)
    if "admin" in payload.scopes:
        require_route_mutation_approval(
            request,
            route_name="auth.api_keys.delete",
            operation="delete",
            arguments={"key_id": key_id},
            details="Admin API key revocation requires an explicit approval token.",
        )
    # Admins can revoke any key; non-admins only their own
    subject = None if "admin" in payload.scopes else payload.sub
    found = revoke_api_key(key_id, requesting_subject=subject)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
