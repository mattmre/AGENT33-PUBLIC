"""Scope-based permission system with deny-first evaluation."""

from __future__ import annotations

import fnmatch
from enum import StrEnum
from typing import Any

from fastapi import Depends, HTTPException, Request, status

# ---------------------------------------------------------------------------
# Defined scopes
# ---------------------------------------------------------------------------

SCOPES: set[str] = {
    "admin",
    "agents:read",
    "agents:write",
    "agents:invoke",
    "workflows:read",
    "workflows:write",
    "workflows:execute",
    "tools:execute",
    "component-security:read",
    "component-security:write",
    "multimodal:read",
    "multimodal:write",
    "multimodal:execute",
    "outcomes:read",
    "outcomes:write",
    "hooks:read",
    "hooks:manage",
    "hooks:admin",
    "plugins:read",
    "plugins:write",
    "operator:read",
    "operator:write",
    "cron:read",
    "cron:write",
    "processes:read",
    "processes:manage",
    "provenance:read",
    "provenance:export",
}


class PermissionDecision(StrEnum):
    """Decision result for permission evaluation."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


def _matches_any_wildcard(scope: str, patterns: list[str]) -> bool:
    """Return True if scope matches any wildcard pattern in patterns."""
    return any(fnmatch.fnmatch(scope, pattern) for pattern in patterns)


def check_permission_decision(
    required_scope: str,
    token_scopes: list[str],
    deny_scopes: list[str] | None = None,
    ask_scopes: list[str] | None = None,
) -> PermissionDecision:
    """Return a decision (ALLOW/ASK/DENY) for the given permission check.

    Evaluation order (deny-first):
    1. If the required scope matches any *deny_scopes* pattern, **DENY**.
    2. If the required scope matches any *ask_scopes* pattern, **ASK**.
    3. The ``admin`` scope implicitly grants all permissions (unless admin itself is denied/asked).
    4. If *required_scope* matches any *token_scopes* pattern, **ALLOW**.
    5. Otherwise, **DENY**.

    Patterns support Unix shell-style wildcards (fnmatch):
    - ``*`` matches everything
    - ``?`` matches any single character
    - ``[seq]`` matches any character in seq
    - ``[!seq]`` matches any character not in seq
    """
    # 1. Check deny patterns (deny overrides everything)
    if deny_scopes and _matches_any_wildcard(required_scope, deny_scopes):
        return PermissionDecision.DENY

    # 2. Check ask patterns (ask blocks execution but may be approved later)
    if ask_scopes and _matches_any_wildcard(required_scope, ask_scopes):
        return PermissionDecision.ASK

    # 3. Admin grants all unless admin itself is explicitly denied/asked
    if _matches_any_wildcard("admin", token_scopes):
        # Check if admin scope is denied
        if deny_scopes and _matches_any_wildcard("admin", deny_scopes):
            return PermissionDecision.DENY
        # Check if admin scope requires approval
        if ask_scopes and _matches_any_wildcard("admin", ask_scopes):
            return PermissionDecision.ASK
        return PermissionDecision.ALLOW

    # 4. Check if token scopes include the required scope (with wildcards)
    if _matches_any_wildcard(required_scope, token_scopes):
        return PermissionDecision.ALLOW

    # 5. Default deny
    return PermissionDecision.DENY


def check_permission(
    required_scope: str,
    token_scopes: list[str],
    deny_scopes: list[str] | None = None,
) -> bool:
    """Return ``True`` if *token_scopes* satisfy *required_scope*.

    Evaluation order (deny-first):
    1. If the required scope is in *deny_scopes*, **deny** immediately.
    2. The ``admin`` scope implicitly grants all permissions (unless denied).
    3. Otherwise, check if *required_scope* is in *token_scopes*.

    This function is backward-compatible and calls check_permission_decision
    internally, treating ASK as DENY for legacy callers.
    """
    decision = check_permission_decision(required_scope, token_scopes, deny_scopes)
    return decision == PermissionDecision.ALLOW


def _get_token_payload(request: Request) -> Any:
    """Extract token payload previously set by auth middleware."""
    payload = getattr(request.state, "user", None)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return payload


def require_scope(scope: str) -> Any:
    """FastAPI dependency that enforces *scope* on the current request.

    Usage::

        @router.get("/agents", dependencies=[Depends(require_scope("agents:read"))])
        async def list_agents(): ...
    """

    async def _checker(request: Request) -> Any:
        payload = _get_token_payload(request)
        if not check_permission(scope, payload.scopes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {scope}",
            )
        return payload

    return Depends(_checker)
