"""P69b: Human-in-the-loop tool approval — data models."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class PausedInvocationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMED_OUT = "timed_out"
    CONSUMED = "consumed"


class PausedInvocation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    invocation_id: str
    tenant_id: str
    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    nonce: str
    status: PausedInvocationStatus = PausedInvocationStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    resolved_at: datetime | None = None
    approved_by: str | None = None


class ToolApprovalTimeout(Exception):  # noqa: N818
    pass


class ToolApprovalDenied(Exception):  # noqa: N818
    pass


class ToolApprovalNonceReplay(Exception):  # noqa: N818
    pass


class ToolApprovalInvalidState(Exception):  # noqa: N818
    pass


class ToolApprovalFeatureDisabled(Exception):  # noqa: N818
    pass


def compute_nonce(
    run_id: str,
    tool_name: str,
    tenant_secret: str,
    *,
    timestamp: float | None = None,
) -> str:
    """HMAC-SHA256(f'{run_id}:{tool_name}:{floor(timestamp/30)}', tenant_secret).

    Returns a 64-character lowercase hexadecimal string.
    """
    import time

    ts = timestamp if timestamp is not None else time.time()
    window = int(ts) // 30
    message = f"{run_id}:{tool_name}:{window}"
    return hmac.new(tenant_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
