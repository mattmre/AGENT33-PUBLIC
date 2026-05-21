"""Messaging data models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    """An inbound message from any platform."""

    platform: str
    channel_id: str
    user_id: str
    text: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class OutgoingMessage(BaseModel):
    """A message to be sent to a platform channel."""

    channel_id: str
    text: str
    reply_to: str | None = None


class PairingRequest(BaseModel):
    """A pairing request linking a platform user to an AGENT-33 account."""

    platform: str
    user_id: str
    code: str
    expires_at: datetime


class ChannelHealthResult(BaseModel):
    """Health check result for a messaging channel."""

    platform: str
    status: Literal["ok", "degraded", "unavailable"]
    latency_ms: float | None = None
    detail: str = ""
    queue_depth: int = 0
