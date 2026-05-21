"""Webhook endpoints for receiving platform messages."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from agent33.security.injection import scan_inputs_recursive

router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)

# These registries are populated at application startup by the bootstrap layer.
# Each maps a platform name to the corresponding adapter instance.
_adapters: dict[str, Any] = {}


def register_adapter(platform: str, adapter: Any) -> None:
    """Register a messaging adapter so the webhook route can dispatch to it."""
    _adapters[platform] = adapter


def _reject_unsafe_payload(payload: object) -> None:
    """Reject external webhook payloads containing prompt-injection attempts."""
    scan = scan_inputs_recursive(payload)
    if not scan.is_safe:
        raise HTTPException(
            status_code=400,
            detail=f"Webhook payload rejected: {', '.join(scan.threats)}",
        )


# -----------------------------------------------------------------------
# Telegram
# -----------------------------------------------------------------------


@router.post("/telegram")
async def telegram_webhook(request: Request) -> dict[str, str]:
    """Receive Telegram Bot API webhook updates."""
    adapter = _adapters.get("telegram")
    if adapter is None:
        raise HTTPException(status_code=503, detail="Telegram adapter not configured")

    payload = await request.json()
    _reject_unsafe_payload(payload)
    adapter.enqueue_webhook_update(payload)
    return {"status": "ok"}


# -----------------------------------------------------------------------
# Discord
# -----------------------------------------------------------------------


@router.post("/discord")
async def discord_webhook(
    request: Request,
    x_signature_ed25519: str = Header(""),
    x_signature_timestamp: str = Header(""),
) -> dict[str, Any]:
    """Receive Discord interaction webhooks."""
    adapter = _adapters.get("discord")
    if adapter is None:
        raise HTTPException(status_code=503, detail="Discord adapter not configured")

    body = await request.body()

    if not adapter.verify_signature(x_signature_ed25519, x_signature_timestamp, body):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()

    # Discord requires a PONG response to type 1 (PING) interactions.
    if payload.get("type") == 1:
        return {"type": 1}

    _reject_unsafe_payload(payload)
    adapter.enqueue_interaction(payload)
    return {"status": "ok"}


# -----------------------------------------------------------------------
# Slack
# -----------------------------------------------------------------------


@router.post("/slack")
async def slack_webhook(
    request: Request,
    x_slack_request_timestamp: str = Header(""),
    x_slack_signature: str = Header(""),
) -> dict[str, Any]:
    """Receive Slack Events API callbacks."""
    adapter = _adapters.get("slack")
    if adapter is None:
        raise HTTPException(status_code=503, detail="Slack adapter not configured")

    body = await request.body()

    if not adapter.verify_signature(x_slack_request_timestamp, body, x_slack_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()

    # Slack URL verification challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    _reject_unsafe_payload(payload)
    adapter.enqueue_event(payload)
    return {"status": "ok"}


# -----------------------------------------------------------------------
# WhatsApp
# -----------------------------------------------------------------------


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
) -> str:
    """Handle WhatsApp webhook verification GET request."""
    adapter = _adapters.get("whatsapp")
    if adapter is None:
        raise HTTPException(status_code=503, detail="WhatsApp adapter not configured")

    result: str | None = adapter.verify_webhook_challenge(
        hub_mode,
        hub_verify_token,
        hub_challenge,
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Verification failed")
    return result


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    x_hub_signature_256: str = Header(""),
) -> dict[str, str]:
    """Receive WhatsApp Cloud API webhook events."""
    adapter = _adapters.get("whatsapp")
    if adapter is None:
        raise HTTPException(status_code=503, detail="WhatsApp adapter not configured")

    body = await request.body()

    if not adapter.verify_signature(x_hub_signature_256, body):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = await request.json()
    _reject_unsafe_payload(payload)
    adapter.enqueue_webhook_payload(payload)
    return {"status": "ok"}


# -----------------------------------------------------------------------
# Signal (via signal-cli-rest-api)
# -----------------------------------------------------------------------


@router.post("/signal")
async def signal_webhook(request: Request) -> dict[str, str]:
    """Receive Signal messages via REST API bridge."""
    adapter = _adapters.get("signal")
    if adapter is None:
        raise HTTPException(status_code=503, detail="Signal adapter not configured")

    payload = await request.json()
    _reject_unsafe_payload(payload)
    adapter.enqueue_message(payload)
    return {"status": "ok"}


# -----------------------------------------------------------------------
# iMessage (via Mac bridge / Webhooks)
# -----------------------------------------------------------------------


@router.post("/imessage")
async def imessage_webhook(request: Request) -> dict[str, str]:
    """Receive incoming Apple iMessages via bridge."""
    adapter = _adapters.get("imessage")
    if adapter is None:
        raise HTTPException(status_code=503, detail="iMessage adapter not configured")

    payload = await request.json()
    _reject_unsafe_payload(payload)
    adapter.enqueue_message(payload)
    return {"status": "ok"}
