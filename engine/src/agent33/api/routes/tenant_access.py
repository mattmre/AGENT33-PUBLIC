"""Shared tenant-context helpers for route-layer authorization checks."""

from __future__ import annotations

from fastapi import HTTPException, Request

from agent33.security.permissions import check_permission


def get_request_tenant_context(request: Request) -> tuple[str, list[str], bool]:
    """Return the current request tenant/scopes plus whether a principal exists."""
    user = getattr(request.state, "user", None)
    if user is None:
        return "", [], False
    return getattr(user, "tenant_id", ""), list(getattr(user, "scopes", [])), True


def require_tenant_context(request: Request) -> tuple[str, list[str]]:
    """Reject authenticated non-admin callers that are missing tenant binding."""
    tenant_id, scopes, has_principal = get_request_tenant_context(request)
    is_admin = check_permission("admin", scopes) if scopes else False
    if has_principal and not is_admin and not tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Tenant context required for authenticated principal",
        )
    return tenant_id, scopes


def tenant_filter_for_request(request: Request) -> str | None:
    """Return the effective tenant filter for the current caller."""
    tenant_id, scopes = require_tenant_context(request)
    is_admin = check_permission("admin", scopes) if scopes else False
    if is_admin:
        return None
    return tenant_id or None
