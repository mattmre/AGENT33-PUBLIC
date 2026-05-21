"""Admin endpoints for webhook delivery reliability monitoring and control."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from agent33.automation.webhook_delivery import (
    DeliveryStats,
    WebhookDeliveryRecord,
    WebhookDeliveryStatus,
)
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/webhooks/deliveries", tags=["webhook-deliveries"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_manager(request: Request) -> Any:
    manager = getattr(request.app.state, "webhook_delivery", None)
    if manager is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook delivery manager not initialized",
        )
    return manager


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class DeliveryListResponse(BaseModel):
    """Paginated list of delivery records."""

    deliveries: list[WebhookDeliveryRecord]
    count: int


class PurgeResponse(BaseModel):
    """Response for purge operation."""

    purged: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=DeliveryListResponse,
    dependencies=[require_scope("admin")],
)
async def list_deliveries(
    request: Request,
    delivery_status: Annotated[WebhookDeliveryStatus | None, Query(alias="status")] = None,
    webhook_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
) -> DeliveryListResponse:
    """List webhook deliveries with optional status and webhook_id filters."""
    manager = _get_manager(request)
    deliveries = manager.list_deliveries(
        status=delivery_status,
        webhook_id=webhook_id,
        limit=limit,
    )
    return DeliveryListResponse(deliveries=deliveries, count=len(deliveries))


@router.get(
    "/stats",
    response_model=DeliveryStats,
    dependencies=[require_scope("admin")],
)
async def delivery_stats(request: Request) -> DeliveryStats:
    """Get aggregate webhook delivery statistics."""
    manager = _get_manager(request)
    stats: DeliveryStats = manager.get_stats()
    return stats


@router.get(
    "/dead-letters",
    response_model=DeliveryListResponse,
    dependencies=[require_scope("admin")],
)
async def list_dead_letters(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
) -> DeliveryListResponse:
    """List dead-lettered webhook deliveries."""
    manager = _get_manager(request)
    dead_letters = manager.get_dead_letters(limit=limit)
    return DeliveryListResponse(deliveries=dead_letters, count=len(dead_letters))


@router.get(
    "/{delivery_id}",
    response_model=WebhookDeliveryRecord,
    dependencies=[require_scope("admin")],
)
async def get_delivery(
    request: Request,
    delivery_id: str,
) -> WebhookDeliveryRecord:
    """Retrieve a single delivery record with all attempt details."""
    manager = _get_manager(request)
    record = manager.get_delivery(delivery_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery {delivery_id} not found",
        )
    result: WebhookDeliveryRecord = record
    return result


@router.post(
    "/{delivery_id}/retry",
    dependencies=[require_scope("admin")],
)
async def retry_delivery(
    request: Request,
    delivery_id: str,
) -> dict[str, str]:
    """Retry a failed or dead-lettered webhook delivery."""
    manager = _get_manager(request)
    try:
        manager.retry_dead_letter(delivery_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Delivery {delivery_id} not found",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from None
    return {"status": "re-enqueued", "delivery_id": delivery_id}


@router.delete(
    "/purge",
    response_model=PurgeResponse,
    dependencies=[require_scope("admin")],
)
async def purge_delivered(
    request: Request,
    older_than_hours: float = Query(default=24.0, ge=0.0),
) -> PurgeResponse:
    """Purge successfully delivered records older than the given threshold."""
    manager = _get_manager(request)
    purged = manager.purge_delivered(older_than_hours=older_than_hours)
    return PurgeResponse(purged=purged)
