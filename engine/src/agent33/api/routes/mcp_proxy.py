"""FastAPI router for MCP proxy server management."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException

from agent33.mcp_server.proxy_models import (
    ProxyFleetConfig,
    ProxyServerConfig,  # noqa: TC001 (FastAPI body)
)
from agent33.security.permissions import require_scope

if TYPE_CHECKING:
    from agent33.mcp_server.proxy_manager import ProxyManager

router = APIRouter(prefix="/v1/mcp/proxy", tags=["mcp-proxy"])

_proxy_manager: ProxyManager | None = None
_config_path: str = ""


def set_proxy_manager(manager: ProxyManager) -> None:
    """Inject the proxy manager (called from lifespan)."""
    global _proxy_manager  # noqa: PLW0603
    _proxy_manager = manager


def set_config_path(path: str) -> None:
    """Inject the config file path (called from lifespan)."""
    global _config_path  # noqa: PLW0603
    _config_path = path


def get_proxy_manager() -> ProxyManager | None:
    """Return the proxy manager singleton."""
    return _proxy_manager


def _require_manager() -> ProxyManager:
    if _proxy_manager is None:
        raise HTTPException(status_code=503, detail="MCP proxy manager not initialized")
    return _proxy_manager


def _read_and_validate_config() -> ProxyFleetConfig:
    """Read and validate the config file.  Raises HTTPException on failure."""
    if not _config_path.strip():
        raise HTTPException(status_code=400, detail="No mcp_proxy_config_path configured")

    config_file = Path(_config_path)
    if not config_file.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Config file not found: {_config_path}",
        )

    try:
        raw = config_file.read_text(encoding="utf-8")
        return ProxyFleetConfig.model_validate_json(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Server management endpoints
# ---------------------------------------------------------------------------


@router.get("/servers", dependencies=[require_scope("agents:read")])
async def list_proxy_servers() -> dict[str, Any]:
    """List all registered proxy servers with health status."""
    manager = _require_manager()
    if manager.health_check_enabled:
        await manager.refresh_health()
    servers = manager.list_servers()
    summary = manager.health_summary()
    return {
        "servers": servers,
        **summary,
    }


@router.get("/servers/{server_id}", dependencies=[require_scope("agents:read")])
async def get_proxy_server(server_id: str) -> dict[str, Any]:
    """Get details and health for a specific proxy server."""
    manager = _require_manager()
    if manager.health_check_enabled:
        await manager.refresh_health()
    handle = manager.get_server(server_id)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"Proxy server '{server_id}' not found")
    return handle.status_summary()


@router.post("/servers", dependencies=[require_scope("admin")])
async def add_proxy_server(config: ProxyServerConfig) -> dict[str, Any]:
    """Register and start a new proxy server."""
    manager = _require_manager()
    try:
        handle = await manager.add_server(config)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return handle.status_summary()


@router.delete("/servers/{server_id}", dependencies=[require_scope("admin")])
async def remove_proxy_server(server_id: str) -> dict[str, Any]:
    """Stop and unregister a proxy server."""
    manager = _require_manager()
    removed = await manager.remove_server(server_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Proxy server '{server_id}' not found")
    return {"id": server_id, "status": "removed"}


@router.post("/servers/{server_id}/restart", dependencies=[require_scope("admin")])
async def restart_proxy_server(server_id: str) -> dict[str, Any]:
    """Restart a specific proxy server with diagnostics."""
    manager = _require_manager()
    handle = manager.get_server(server_id)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"Proxy server '{server_id}' not found")

    previous_state = handle.state.value
    t0 = time.monotonic()
    await handle.stop()
    await handle.start()
    restart_duration_ms = round((time.monotonic() - t0) * 1000, 2)

    summary = handle.status_summary()
    summary["restart_duration_ms"] = restart_duration_ms
    summary["previous_state"] = previous_state
    return summary


# ---------------------------------------------------------------------------
# Fleet-level operations
# ---------------------------------------------------------------------------


@router.post("/restart", dependencies=[require_scope("admin")])
async def fleet_restart() -> dict[str, Any]:
    """Restart ALL enabled proxy servers."""
    manager = _require_manager()
    return await manager.restart_all()


@router.post("/reload-config", dependencies=[require_scope("admin")])
async def reload_config() -> dict[str, Any]:
    """Re-read config file and apply changes to the running fleet.

    - New servers are added and started.
    - Removed servers are stopped and unregistered.
    - Changed servers are restarted with new config.
    - Invalid config is rejected without affecting running servers.
    """
    manager = _require_manager()
    new_config = _read_and_validate_config()
    return await manager.reload_config(new_config)


@router.post("/validate-config", dependencies=[require_scope("admin")])
async def validate_config() -> dict[str, Any]:
    """Validate the config file without applying changes.

    Returns what *would* change if reload-config were called.
    """
    manager = _require_manager()

    if not _config_path.strip():
        return {
            "valid": False,
            "server_count": 0,
            "errors": ["No mcp_proxy_config_path configured"],
            "diff": {},
        }

    config_file = Path(_config_path)
    if not config_file.exists():
        return {
            "valid": False,
            "server_count": 0,
            "errors": [f"Config file not found: {_config_path}"],
            "diff": {},
        }

    try:
        raw = config_file.read_text(encoding="utf-8")
        new_config = ProxyFleetConfig.model_validate_json(raw)
    except Exception as exc:
        return {
            "valid": False,
            "server_count": 0,
            "errors": [str(exc)],
            "diff": {},
        }

    diff = manager.diff_config(new_config)
    return {
        "valid": True,
        "server_count": len(new_config.proxy_servers),
        "errors": [],
        "diff": diff,
    }


# ---------------------------------------------------------------------------
# Tool and health endpoints
# ---------------------------------------------------------------------------


@router.get("/tools", dependencies=[require_scope("agents:read")])
async def list_proxy_tools() -> dict[str, Any]:
    """List all aggregated proxy tools."""
    manager = _require_manager()
    if manager.health_check_enabled:
        await manager.refresh_health()
    tools = manager.list_aggregated_tools()
    return {"tools": tools, "count": len(tools)}


@router.get("/health")
async def proxy_fleet_health() -> dict[str, Any]:
    """Fleet-level health summary (public)."""
    manager = _require_manager()
    if manager.health_check_enabled:
        await manager.refresh_health()
    return manager.health_summary()
