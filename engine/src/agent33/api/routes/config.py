"""Config schema introspection and apply API routes (Track 9)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from agent33.config import Settings
from agent33.config_apply import ConfigApplyRequest, ConfigApplyResult, ConfigApplyService
from agent33.config_schema import ConfigSchemaResponse, introspect_settings_schema
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/config", tags=["config"])


# ---------------------------------------------------------------------------
# Schema introspection
# ---------------------------------------------------------------------------


@router.get(
    "/schema",
    response_model=ConfigSchemaResponse,
    dependencies=[require_scope("operator:read")],
)
async def config_schema() -> ConfigSchemaResponse:
    """Return the full configuration schema grouped by subsystem."""
    return introspect_settings_schema(Settings)


@router.get(
    "/schema/{group}",
    response_model=ConfigSchemaResponse,
    dependencies=[require_scope("operator:read")],
)
async def config_schema_group(group: str) -> ConfigSchemaResponse:
    """Return the configuration schema for a single group."""
    full = introspect_settings_schema(Settings)
    if group not in full.groups:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Config group {group!r} not found. Available groups: {sorted(full.groups.keys())}"
            ),
        )
    group_fields = full.groups[group]
    return ConfigSchemaResponse(
        groups={group: group_fields},
        total_fields=len(group_fields),
    )


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


@router.post(
    "/apply",
    response_model=ConfigApplyResult,
    dependencies=[require_scope("operator:write")],
)
async def config_apply(
    request: Request,
    body: ConfigApplyRequest,
) -> ConfigApplyResult:
    """Apply configuration changes at runtime (admin only).

    Changes are applied to the live Settings singleton. Infrastructure fields
    (database_url, redis_url, etc.) are flagged as requiring a restart.
    """
    svc: ConfigApplyService | None = getattr(request.app.state, "config_apply_service", None)
    if svc is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Config apply service not initialized",
        )
    return svc.apply(body)
