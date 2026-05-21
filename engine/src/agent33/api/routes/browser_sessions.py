"""Browser session management API routes."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Request

from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/browser", tags=["browser"])


@router.get("/sessions", dependencies=[require_scope("operator:read")])
async def list_browser_sessions(request: Request) -> dict[str, Any]:
    """List active browser sessions for the current tenant."""
    from agent33.tools.builtin.browser import _sessions

    user = getattr(request.state, "user", None)
    tenant_id = (user.tenant_id if user is not None and hasattr(user, "tenant_id") else "") or ""
    now = time.monotonic()
    sessions = []
    for sid, sess in _sessions.items():
        if tenant_id and sess.tenant_id and sess.tenant_id != tenant_id:
            continue
        sessions.append(
            {
                "session_id": sid,
                "tenant_id": sess.tenant_id or "",
                "idle_seconds": int(now - sess.last_used),
            }
        )
    return {"sessions": sessions, "count": len(sessions)}
