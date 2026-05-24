"""Phase 23 public user lifecycle administration API."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, SecretStr

from agent33.api.route_approvals import require_route_mutation_approval
from agent33.security.auth_repository import get_auth_repository
from agent33.security.permissions import _get_token_payload, require_scope
from agent33.tools.approvals import ApprovalRiskTier

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/users", tags=["users"])


class UserCreateRequest(BaseModel):
    """Body for creating an auth user."""

    username: str = Field(..., min_length=1, max_length=160)
    password: SecretStr = Field(..., min_length=8)
    tenant_id: str = Field(..., min_length=1, max_length=120)
    role: str = Field(default="user", max_length=80)
    scopes: list[str] = Field(default_factory=list)
    enabled: bool = True


class UserUpdateRequest(BaseModel):
    """Body for patching an auth user."""

    password: SecretStr | None = Field(default=None, min_length=8)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, max_length=80)
    scopes: list[str] | None = None
    enabled: bool | None = None


class UserRoleRequest(BaseModel):
    """Body for role/scope assignment."""

    role: str = Field(..., min_length=1, max_length=80)
    scopes: list[str] = Field(default_factory=list)


class UserTenantRequest(BaseModel):
    """Body for tenant reassignment."""

    tenant_id: str = Field(..., min_length=1, max_length=120)


class UserResponse(BaseModel):
    """Safe user lifecycle response."""

    username: str
    tenant_id: str
    role: str
    scopes: list[str]
    enabled: bool


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100_000).hex()


def _sanitize_user(user: dict[str, Any]) -> UserResponse:
    return UserResponse(
        username=str(user.get("username", "")),
        tenant_id=str(user.get("tenant_id", "")),
        role=str(user.get("role", "user")),
        scopes=list(user.get("scopes", [])),
        enabled=bool(user.get("enabled", True)),
    )


def _normalized_scopes(role: str, scopes: list[str]) -> list[str]:
    normalized = list(dict.fromkeys(scope.strip() for scope in scopes if scope.strip()))
    if role == "admin" and "admin" not in normalized:
        normalized.insert(0, "admin")
    return normalized


def _create_approval_args(body: UserCreateRequest) -> dict[str, Any]:
    return {
        "username": body.username,
        "tenant_id": body.tenant_id,
        "role": body.role,
        "scopes": _normalized_scopes(body.role, body.scopes),
        "enabled": body.enabled,
    }


def _update_approval_args(username: str, body: UserUpdateRequest) -> dict[str, Any]:
    args = body.model_dump(mode="json", exclude_none=True, exclude={"password"})
    args["username"] = username
    return args


def _get_user_or_404(username: str) -> dict[str, Any]:
    user = get_auth_repository().get_user(username)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    return user


def _set_user(username: str, user: dict[str, Any]) -> dict[str, Any]:
    get_auth_repository().set_user(username, user)
    updated = get_auth_repository().get_user(username)
    if updated is None:  # pragma: no cover - repository contract guard
        raise HTTPException(status_code=500, detail="User update failed")
    return updated


@router.get("/", dependencies=[require_scope("admin")])
async def list_users(tenant_id: str | None = None) -> list[UserResponse]:
    """List users, optionally filtered by tenant."""
    return [_sanitize_user(user) for user in get_auth_repository().list_users(tenant_id=tenant_id)]


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_scope("admin")],
)
async def create_user(body: UserCreateRequest, request: Request) -> UserResponse:
    """Create a user with tenant, role, scope, and enabled-state fields."""
    approval_args = _create_approval_args(body)
    require_route_mutation_approval(
        request,
        route_name="users.create",
        operation="create",
        arguments=approval_args,
        details="User creation changes authentication and tenant access state.",
        risk_tier=ApprovalRiskTier.HIGH,
    )
    repo = get_auth_repository()
    salt = secrets.token_bytes(16)
    try:
        user = repo.create_user(
            username=body.username,
            password_hash=_hash_password(body.password.get_secret_value(), salt),
            tenant_id=body.tenant_id,
            role=body.role,
            salt=salt.hex(),
            scopes=approval_args["scopes"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    user["enabled"] = body.enabled
    repo.set_user(body.username, user)
    logger.info("user_lifecycle_created", username=body.username, tenant_id=body.tenant_id)
    return _sanitize_user(user)


@router.get("/{username}", dependencies=[require_scope("admin")])
async def get_user(username: str) -> UserResponse:
    """Get one user lifecycle record without secrets."""
    return _sanitize_user(_get_user_or_404(username))


@router.patch("/{username}", dependencies=[require_scope("admin")])
async def update_user(
    username: str,
    body: UserUpdateRequest,
    request: Request,
) -> UserResponse:
    """Patch password, tenant, role, scopes, and enabled state for a user."""
    require_route_mutation_approval(
        request,
        route_name="users.update",
        operation="update",
        arguments=_update_approval_args(username, body),
        details="User lifecycle updates require explicit operator approval.",
        risk_tier=ApprovalRiskTier.HIGH,
    )
    user = dict(_get_user_or_404(username))
    if body.password is not None:
        salt = secrets.token_bytes(16)
        user["salt"] = salt.hex()
        user["password_hash"] = _hash_password(body.password.get_secret_value(), salt)
    if body.tenant_id is not None:
        user["tenant_id"] = body.tenant_id
    if body.role is not None:
        user["role"] = body.role
    if body.scopes is not None:
        role = str(user.get("role", "user"))
        user["scopes"] = _normalized_scopes(role, body.scopes)
    if body.enabled is not None:
        user["enabled"] = body.enabled
    logger.info("user_lifecycle_updated", username=username)
    return _sanitize_user(_set_user(username, user))


@router.post("/{username}/disable", dependencies=[require_scope("admin")])
async def disable_user(username: str, request: Request) -> UserResponse:
    """Disable a user without deleting the audit-visible record."""
    payload = _get_token_payload(request)
    if hmac.compare_digest(username, str(payload.sub)):
        raise HTTPException(status_code=409, detail="Admins cannot disable their own active token")
    require_route_mutation_approval(
        request,
        route_name="users.disable",
        operation="disable",
        arguments={"username": username, "enabled": False},
        details="Disabling a user changes authentication access.",
        risk_tier=ApprovalRiskTier.HIGH,
    )
    user = dict(_get_user_or_404(username))
    user["enabled"] = False
    logger.info("user_lifecycle_disabled", username=username)
    return _sanitize_user(_set_user(username, user))


@router.post("/{username}/enable", dependencies=[require_scope("admin")])
async def enable_user(username: str, request: Request) -> UserResponse:
    """Enable a disabled user."""
    require_route_mutation_approval(
        request,
        route_name="users.enable",
        operation="enable",
        arguments={"username": username, "enabled": True},
        details="Enabling a user changes authentication access.",
        risk_tier=ApprovalRiskTier.HIGH,
    )
    user = dict(_get_user_or_404(username))
    user["enabled"] = True
    logger.info("user_lifecycle_enabled", username=username)
    return _sanitize_user(_set_user(username, user))


@router.post("/{username}/roles", dependencies=[require_scope("admin")])
async def assign_user_role(
    username: str,
    body: UserRoleRequest,
    request: Request,
) -> UserResponse:
    """Assign a role and scopes to a user."""
    scopes = _normalized_scopes(body.role, body.scopes)
    require_route_mutation_approval(
        request,
        route_name="users.roles.assign",
        operation="assign",
        arguments={"username": username, "role": body.role, "scopes": scopes},
        details="Role assignment changes user authorization.",
        risk_tier=ApprovalRiskTier.HIGH,
    )
    user = dict(_get_user_or_404(username))
    user["role"] = body.role
    user["scopes"] = scopes
    logger.info("user_lifecycle_role_assigned", username=username, role=body.role)
    return _sanitize_user(_set_user(username, user))


@router.post("/{username}/tenant", dependencies=[require_scope("admin")])
async def reassign_user_tenant(
    username: str,
    body: UserTenantRequest,
    request: Request,
) -> UserResponse:
    """Reassign a user to another tenant."""
    require_route_mutation_approval(
        request,
        route_name="users.tenant.assign",
        operation="assign",
        arguments={"username": username, "tenant_id": body.tenant_id},
        details="Tenant reassignment changes data access boundaries.",
        risk_tier=ApprovalRiskTier.HIGH,
    )
    user = dict(_get_user_or_404(username))
    user["tenant_id"] = body.tenant_id
    logger.info("user_lifecycle_tenant_assigned", username=username, tenant_id=body.tenant_id)
    return _sanitize_user(_set_user(username, user))


@router.delete(
    "/{username}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_scope("admin")],
    response_model=None,
)
async def delete_user(username: str, request: Request) -> None:
    """Delete a user lifecycle record."""
    payload = _get_token_payload(request)
    if hmac.compare_digest(username, str(payload.sub)):
        raise HTTPException(status_code=409, detail="Admins cannot delete their own active token")
    require_route_mutation_approval(
        request,
        route_name="users.delete",
        operation="delete",
        arguments={"username": username},
        details="User deletion removes authentication state.",
        risk_tier=ApprovalRiskTier.HIGH,
    )
    if not get_auth_repository().delete_user(username):
        raise HTTPException(status_code=404, detail=f"User '{username}' not found")
    logger.info("user_lifecycle_deleted", username=username)
