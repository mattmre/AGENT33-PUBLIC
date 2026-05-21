"""GET /v1/policy/active — return current active policy posture."""

from __future__ import annotations

from fastapi import APIRouter, Request

from agent33.security.permissions import require_scope
from agent33.security.policy import get_active_policy

router = APIRouter(prefix="/v1/policy", tags=["policy"])


@router.get("/active", dependencies=[require_scope("agents:read")])
async def get_active_policy_route(request: Request) -> dict:  # type: ignore[type-arg]
    """Return the active policy state derived from runtime configuration."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from agent33.config import settings as _settings

        settings = _settings
    policy = get_active_policy(settings)
    return policy.model_dump()
