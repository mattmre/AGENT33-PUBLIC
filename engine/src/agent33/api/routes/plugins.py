"""FastAPI router for plugin lifecycle management endpoints."""

# NOTE: no ``from __future__ import annotations`` -- Pydantic needs these
# types at runtime for request-body validation.

from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request, status

from agent33.api.routes.tenant_access import tenant_filter_for_request
from agent33.plugins.api_models import (
    PluginConfigUpdate,
    PluginDetail,
    PluginDiscoverResponse,
    PluginDoctorReportResponse,
    PluginDoctorSummaryResponse,
    PluginEventsResponse,
    PluginHealthResponse,
    PluginInstallRequest,
    PluginInstallResponse,
    PluginLifecycleEventResponse,
    PluginPermissionInventory,
    PluginSearchResponse,
    PluginSummary,
)
from agent33.plugins.installer import PluginInstallMode
from agent33.plugins.models import PluginState
from agent33.security.permissions import require_scope

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])


def _get_plugin_registry(request: Request) -> Any:
    """Extract plugin registry from app state."""
    registry = getattr(request.app.state, "plugin_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin registry not initialized",
        )
    return registry


def _get_plugin_installer(request: Request) -> Any:
    installer = getattr(request.app.state, "plugin_installer", None)
    if installer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin installer not initialized",
        )
    return installer


def _get_plugin_config_store(request: Request) -> Any:
    store = getattr(request.app.state, "plugin_config_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin config store not initialized",
        )
    return store


def _get_plugin_doctor(request: Request) -> Any:
    doctor = getattr(request.app.state, "plugin_doctor", None)
    if doctor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin doctor not initialized",
        )
    return doctor


def _get_plugin_event_store(request: Request) -> Any:
    store = getattr(request.app.state, "plugin_event_store", None)
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin event store not initialized",
        )
    return store


def _request_user(request: Request) -> tuple[str, str | None]:
    user = getattr(request.state, "user", None)
    requested_by = getattr(user, "sub", "") if user is not None else ""
    tenant_id = tenant_filter_for_request(request)
    return requested_by, tenant_id


def _manifest_to_summary(manifest: Any, state: str) -> PluginSummary:
    """Convert a PluginManifest + state into a PluginSummary."""
    contributions = manifest.contributions
    return PluginSummary(
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        state=state,
        author=manifest.author,
        tags=manifest.tags,
        contributions_summary={
            "skills": len(contributions.skills),
            "tools": len(contributions.tools),
            "agents": len(contributions.agents),
            "hooks": len(contributions.hooks),
        },
    )


def _permission_inventory(entry: Any) -> PluginPermissionInventory:
    requested = sorted(permission.value for permission in entry.manifest.permissions)
    if entry.instance is None:
        granted: list[str] = []
        denied: list[str] = []
    else:
        granted = sorted(entry.instance.context.granted_permissions)
        denied = sorted(set(requested) - set(granted))
    return PluginPermissionInventory(
        plugin_name=entry.manifest.name,
        requested=requested,
        granted=granted,
        denied=denied,
    )


@router.get(
    "",
    response_model=list[PluginSummary],
    dependencies=[require_scope("plugins:read")],
)
async def list_plugins(request: Request) -> list[PluginSummary]:
    """List all discovered plugins."""
    registry = _get_plugin_registry(request)
    summaries: list[PluginSummary] = []
    tenant_id = tenant_filter_for_request(request) or ""
    for manifest in registry.list_all(tenant_id=tenant_id):
        state = registry.get_state(manifest.name, tenant_id=tenant_id)
        summaries.append(_manifest_to_summary(manifest, state.value if state else "unknown"))
    return summaries


@router.get(
    "/search",
    response_model=PluginSearchResponse,
    dependencies=[require_scope("plugins:read")],
)
async def search_plugins(request: Request, q: str = "") -> PluginSearchResponse:
    """Search plugins by query string."""
    registry = _get_plugin_registry(request)
    tenant_id = tenant_filter_for_request(request) or ""
    manifests = registry.list_all(tenant_id=tenant_id) if not q else registry.search(q)
    manifests = [
        manifest for manifest in manifests if registry.get(manifest.name, tenant_id=tenant_id)
    ]

    summaries: list[PluginSummary] = []
    for manifest in manifests:
        state = registry.get_state(manifest.name, tenant_id=tenant_id)
        summaries.append(_manifest_to_summary(manifest, state.value if state else "unknown"))

    return PluginSearchResponse(
        query=q,
        count=len(summaries),
        plugins=summaries,
    )


@router.post(
    "/install",
    response_model=PluginInstallResponse,
    dependencies=[require_scope("admin")],
)
async def install_plugin(request: Request, body: PluginInstallRequest) -> PluginInstallResponse:
    """Install or link a plugin from a local source path."""
    installer = _get_plugin_installer(request)
    requested_by, _ = _request_user(request)
    result = await installer.install_from_local(
        Path(body.source_path),
        mode=body.mode,
        requested_by=requested_by,
        enable=body.enable,
    )
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(result.errors)
        )
    return PluginInstallResponse.model_validate(result.model_dump(mode="json"))


@router.get(
    "/doctor",
    response_model=PluginDoctorSummaryResponse,
    dependencies=[require_scope("plugins:read")],
)
async def doctor_plugins(request: Request) -> PluginDoctorSummaryResponse:
    """Run diagnostics across all visible plugins."""
    doctor = _get_plugin_doctor(request)
    reports = await doctor.diagnose_all(tenant_id=tenant_filter_for_request(request) or "")
    return PluginDoctorSummaryResponse(
        count=len(reports),
        reports=[
            PluginDoctorReportResponse.model_validate(report.model_dump(mode="json"))
            for report in reports
        ],
    )


@router.post(
    "/discover",
    response_model=PluginDiscoverResponse,
    dependencies=[require_scope("admin")],
)
async def discover_plugins(request: Request) -> PluginDiscoverResponse:
    """Re-scan plugin directories for new plugins. Requires admin scope."""
    registry = _get_plugin_registry(request)

    from agent33.config import settings

    plugin_dir = Path(getattr(settings, "plugin_definitions_dir", "plugins"))
    discovered = registry.discover(plugin_dir)
    return PluginDiscoverResponse(
        discovered=discovered,
        total=registry.count,
    )


@router.get(
    "/{name}",
    response_model=PluginDetail,
    dependencies=[require_scope("plugins:read")],
)
async def get_plugin(request: Request, name: str) -> PluginDetail:
    """Get detailed plugin info."""
    registry = _get_plugin_registry(request)
    tenant_id = tenant_filter_for_request(request) or ""
    entry = registry.get(name, tenant_id=tenant_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{name}' not found",
        )

    manifest = entry.manifest
    contributions = manifest.contributions
    permission_inventory = _permission_inventory(entry)
    config_store = _get_plugin_config_store(request)
    stored_config = config_store.get(name, tenant_id=tenant_id)

    return PluginDetail(
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        author=manifest.author,
        license=manifest.license,
        homepage=manifest.homepage,
        repository=manifest.repository,
        state=entry.state.value,
        status=manifest.status.value,
        permissions=permission_inventory.requested,
        granted_permissions=permission_inventory.granted,
        denied_permissions=permission_inventory.denied,
        contributions={
            "skills": contributions.skills,
            "tools": contributions.tools,
            "agents": contributions.agents,
            "hooks": contributions.hooks,
        },
        dependencies=[
            {
                "name": dependency.name,
                "version_constraint": dependency.version_constraint,
                "optional": dependency.optional,
            }
            for dependency in manifest.dependencies
        ],
        tags=manifest.tags,
        tenant_config=stored_config.model_dump(mode="json") if stored_config is not None else None,
        error=entry.error,
    )


@router.post(
    "/{name}/enable",
    response_model=PluginSummary,
    dependencies=[require_scope("plugins:write")],
)
async def enable_plugin(request: Request, name: str) -> PluginSummary:
    """Enable a loaded/disabled plugin."""
    registry = _get_plugin_registry(request)
    _, tenant_id = _request_user(request)
    entry = registry.get(name, tenant_id=tenant_id or "")
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{name}' not found",
        )

    try:
        await registry.enable(name, tenant_id=tenant_id or "")
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
                if isinstance(exc, PermissionError)
                else status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc

    entry = registry.get(name, tenant_id=tenant_id or "")
    return _manifest_to_summary(entry.manifest, entry.state.value)


@router.post(
    "/{name}/disable",
    response_model=PluginSummary,
    dependencies=[require_scope("plugins:write")],
)
async def disable_plugin(request: Request, name: str) -> PluginSummary:
    """Disable an active plugin."""
    registry = _get_plugin_registry(request)
    _, tenant_id = _request_user(request)
    entry = registry.get(name, tenant_id=tenant_id or "")
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{name}' not found",
        )

    try:
        await registry.disable(name, tenant_id=tenant_id or "")
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
                if isinstance(exc, PermissionError)
                else status.HTTP_409_CONFLICT
            ),
            detail=str(exc),
        ) from exc

    entry = registry.get(name, tenant_id=tenant_id or "")
    return _manifest_to_summary(entry.manifest, entry.state.value)


@router.post(
    "/{name}/reload",
    response_model=PluginSummary,
    dependencies=[require_scope("admin")],
)
async def reload_plugin(request: Request, name: str) -> PluginSummary:
    """Unload and reload a plugin (hot reload). Requires admin scope."""
    registry = _get_plugin_registry(request)
    entry = registry.get(name)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{name}' not found",
        )

    context_factory = getattr(request.app.state, "plugin_context_factory", None)
    if context_factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Plugin context factory not available for reload",
        )

    try:
        await registry.unload(name)
        await registry.load(name, context_factory, tenant_id=entry.tenant_id)
        await registry.enable(name, tenant_id=entry.tenant_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reload failed: {exc}",
        ) from exc

    entry = registry.get(name)
    return _manifest_to_summary(entry.manifest, entry.state.value)


@router.post(
    "/{name}/update",
    response_model=PluginInstallResponse,
    dependencies=[require_scope("admin")],
)
async def update_plugin(request: Request, name: str) -> PluginInstallResponse:
    """Refresh a managed plugin from its recorded source path."""
    installer = _get_plugin_installer(request)
    requested_by, _ = _request_user(request)
    result = await installer.update(name, requested_by=requested_by)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(result.errors)
        )
    return PluginInstallResponse.model_validate(result.model_dump(mode="json"))


@router.post(
    "/{name}/link",
    response_model=PluginInstallResponse,
    dependencies=[require_scope("admin")],
)
async def link_plugin(
    request: Request,
    name: str,
    body: PluginInstallRequest,
) -> PluginInstallResponse:
    """Link a plugin from a local source path."""
    if body.mode != PluginInstallMode.LINK:
        body = body.model_copy(update={"mode": PluginInstallMode.LINK})
    installer = _get_plugin_installer(request)
    requested_by, _ = _request_user(request)
    result = await installer.install_from_local(
        Path(body.source_path),
        mode=PluginInstallMode.LINK,
        requested_by=requested_by,
        enable=body.enable,
    )
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="; ".join(result.errors)
        )
    if result.plugin_name != name:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Linked plugin manifest name '{result.plugin_name}' did not match '{name}'",
        )
    return PluginInstallResponse.model_validate(result.model_dump(mode="json"))


@router.get(
    "/{name}/config",
    dependencies=[require_scope("plugins:read")],
)
async def get_plugin_config(request: Request, name: str) -> dict[str, Any]:
    """Get persisted plugin configuration for the current tenant context."""
    registry = _get_plugin_registry(request)
    _, tenant_id = _request_user(request)
    entry = registry.get(name, tenant_id=tenant_id or "")
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{name}' not found",
        )

    store = _get_plugin_config_store(request)
    config = store.get(name, tenant_id=tenant_id or "")
    return config.model_dump(mode="json") if config is not None else {}


@router.put(
    "/{name}/config",
    dependencies=[require_scope("plugins:write")],
)
async def update_plugin_config(
    request: Request, name: str, update: PluginConfigUpdate
) -> dict[str, Any]:
    """Persist plugin configuration and optional permission overrides."""
    registry = _get_plugin_registry(request)
    _, tenant_id = _request_user(request)
    entry = registry.get(name, tenant_id=tenant_id or "")
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{name}' not found",
        )

    store = _get_plugin_config_store(request)
    config = store.put(
        name,
        tenant_id=tenant_id or "",
        enabled=update.enabled,
        config_overrides=update.config,
        permission_overrides=update.permission_overrides,
    )
    if entry.instance is not None and tenant_id == entry.tenant_id:
        entry.instance.context.plugin_config.clear()
        entry.instance.context.plugin_config.update(config.config_overrides)
    if update.enabled is True and entry.state in {PluginState.LOADED, PluginState.DISABLED}:
        await registry.enable(name, tenant_id=tenant_id or "")
    elif update.enabled is False and entry.state == PluginState.ACTIVE:
        await registry.disable(name, tenant_id=tenant_id or "")

    event_store = _get_plugin_event_store(request)
    event_store.record(
        "config_updated",
        name,
        version=entry.manifest.version,
        details={
            "tenant_id": tenant_id or "",
            "requested_by": getattr(request.state.user, "sub", ""),
        },
    )
    return {
        "plugin_name": name,
        "updated": True,
        "config": config.config_overrides,
        "enabled": config.enabled,
        "permission_overrides": config.permission_overrides,
        "tenant_id": config.tenant_id,
    }


@router.get(
    "/{name}/health",
    response_model=PluginHealthResponse,
    dependencies=[require_scope("plugins:read")],
)
async def get_plugin_health(request: Request, name: str) -> PluginHealthResponse:
    """Get plugin health status."""
    registry = _get_plugin_registry(request)
    tenant_id = tenant_filter_for_request(request) or ""
    entry = registry.get(name, tenant_id=tenant_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{name}' not found",
        )

    healthy = entry.state == PluginState.ACTIVE
    details: dict[str, Any] = {
        "state": entry.state.value,
        "version": entry.manifest.version,
    }
    if entry.error:
        details["error"] = entry.error
        healthy = False

    if entry.instance is not None and hasattr(entry.instance, "health_check"):
        try:
            check_result = await entry.instance.health_check()
            if isinstance(check_result, dict):
                details.update(check_result)
                healthy = check_result.get("healthy", healthy)
        except Exception as exc:
            details["health_check_error"] = str(exc)
            healthy = False

    return PluginHealthResponse(
        plugin_name=name,
        healthy=healthy,
        details=details,
    )


@router.get(
    "/{name}/doctor",
    response_model=PluginDoctorReportResponse,
    dependencies=[require_scope("plugins:read")],
)
async def doctor_plugin(request: Request, name: str) -> PluginDoctorReportResponse:
    """Run diagnostics for one plugin."""
    doctor = _get_plugin_doctor(request)
    tenant_id = tenant_filter_for_request(request) or ""
    try:
        report = await doctor.diagnose(name, tenant_id=tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return PluginDoctorReportResponse.model_validate(report.model_dump(mode="json"))


@router.get(
    "/{name}/permissions",
    response_model=PluginPermissionInventory,
    dependencies=[require_scope("plugins:read")],
)
async def get_plugin_permissions(request: Request, name: str) -> PluginPermissionInventory:
    """Return requested, granted, and denied plugin permissions."""
    registry = _get_plugin_registry(request)
    tenant_id = tenant_filter_for_request(request) or ""
    entry = registry.get(name, tenant_id=tenant_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{name}' not found",
        )
    return _permission_inventory(entry)


@router.get(
    "/{name}/events",
    response_model=PluginEventsResponse,
    dependencies=[require_scope("plugins:read")],
)
async def list_plugin_events(
    request: Request,
    name: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> PluginEventsResponse:
    """Return lifecycle events for one plugin."""
    registry = _get_plugin_registry(request)
    tenant_id = tenant_filter_for_request(request) or ""
    entry = registry.get(name, tenant_id=tenant_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plugin '{name}' not found",
        )
    event_store = _get_plugin_event_store(request)
    events = event_store.list(plugin_name=name, limit=limit)
    return PluginEventsResponse(
        plugin_name=name,
        count=len(events),
        events=[
            PluginLifecycleEventResponse.model_validate(event.model_dump(mode="json"))
            for event in events
        ],
    )
