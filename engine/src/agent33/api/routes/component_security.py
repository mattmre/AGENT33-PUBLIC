"""FastAPI router for component security scan runs."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from agent33.component_security.llm_security import LLMSecurityScanner
from agent33.component_security.mcp_scanner import MCPSecurityScanner
from agent33.component_security.models import (
    FindingSeverity,
    RunStatus,
    ScanOptions,
    ScanTarget,
    SecurityFinding,
    SecurityProfile,
)
from agent33.component_security.persistence import SecurityScanStore
from agent33.config import settings
from agent33.llm.runtime_config import resolve_default_model
from agent33.security.permissions import require_scope
from agent33.services.security_scan import (
    RunNotFoundError,
    RunStateError,
    SecurityScanError,
    SecurityScanService,
)

router = APIRouter(prefix="/v1/component-security", tags=["component-security"])
_WORKSPACE_ROOT = Path(__file__).resolve().parents[5]
logger = logging.getLogger(__name__)


_service: SecurityScanService | None = None
_mcp_scanner = MCPSecurityScanner()
_llm_scanner = LLMSecurityScanner()
_init_status: dict[str, Any] = {
    "status": "uninitialized",
    "service": "component-security",
    "reason": "Component security service has not been initialized.",
}


def _build_security_scan_store(cfg: Any = None) -> SecurityScanStore | None:
    """Construct optional persistent store for security scan runs."""
    cfg = cfg or settings
    if not cfg.component_security_scan_store_enabled:
        return None
    db_path = cfg.component_security_scan_store_db_path.strip()
    if not db_path:
        return None
    return SecurityScanStore(db_path=db_path)


def init_component_security_service(app: Any, cfg: Any = None) -> None:
    """Initialize the component-security service during app lifespan.

    Stores the service on ``app.state.security_scan_service`` and
    optionally the store on ``app.state.security_scan_store`` for
    proper shutdown cleanup.
    """
    global _service  # noqa: PLW0603
    cfg = cfg or settings
    global _init_status  # noqa: PLW0603
    try:
        store = _build_security_scan_store(cfg)
        _service = SecurityScanService(
            allowed_roots=[str(_WORKSPACE_ROOT)],
            store=store,
            store_retention_days=cfg.component_security_scan_store_retention_days,
            mcp_scanner=_mcp_scanner,
        )
    except Exception as exc:
        logger.exception("component_security_service_init_failed")
        _service = None
        _init_status = {
            "status": "unavailable",
            "service": "component-security",
            "reason": f"Security scan service initialization failed: {exc}",
            "required_action": "Fix component security scan store configuration and restart.",
        }
        app.state.security_scan_service = None
        app.state.security_scan_store = None
        app.state.security_scan_status = _init_status
        return

    _init_status = {
        "status": "ready",
        "service": "component-security",
        "store_enabled": store is not None,
    }
    app.state.security_scan_service = _service
    app.state.security_scan_store = store
    app.state.security_scan_status = _init_status


def get_component_security_service() -> SecurityScanService:
    """Return the component security service.

    Falls back to a default in-memory service if init_component_security_service
    was not called (e.g., during isolated tests).
    """
    global _service  # noqa: PLW0603
    if _service is None:
        _service = SecurityScanService(
            allowed_roots=[str(_WORKSPACE_ROOT)],
            mcp_scanner=_mcp_scanner,
        )
    return _service


def require_initialized_component_security_service(request: Request) -> SecurityScanService:
    """Return initialized component-security service or fail closed."""
    svc: SecurityScanService | None = getattr(request.app.state, "security_scan_service", None)
    if svc is not None:
        return svc
    if _service is not None:
        return _service
    raise HTTPException(
        status_code=503,
        detail={
            "status": "unavailable",
            "service": "component-security",
            "reason": getattr(
                request.app.state,
                "security_scan_status",
                _init_status,
            ).get("reason", "Security scan service is not initialized"),
            "required_action": "Initialize component security service before using scan APIs.",
        },
    )


def _reset_service() -> None:
    """Rebuild the component-security singleton for tests."""
    global _service  # noqa: PLW0603
    _service = SecurityScanService(
        allowed_roots=[str(_WORKSPACE_ROOT)],
        store=_build_security_scan_store(),
        store_retention_days=settings.component_security_scan_store_retention_days,
        mcp_scanner=_mcp_scanner,
    )


@router.get("/health", dependencies=[require_scope("component-security:read")])
async def component_security_health(request: Request) -> dict[str, Any]:
    """Return component-security initialization health."""
    svc: SecurityScanService | None = getattr(request.app.state, "security_scan_service", None)
    if svc is not None:
        status_payload = getattr(request.app.state, "security_scan_status", None) or {
            "status": "ready",
            "service": "component-security",
        }
        return {**status_payload, "initialized": True}
    if _service is not None:
        return {
            "status": "ready",
            "service": "component-security",
            "initialized": True,
            "source": "module-fallback",
        }
    status_payload = getattr(request.app.state, "security_scan_status", None) or _init_status
    return {**status_payload, "initialized": False}


def _tenant_id(request: Request) -> str:
    """Extract tenant ID from authenticated principal."""
    user = getattr(request.state, "user", None)
    if user is None:
        return ""
    return getattr(user, "tenant_id", "")


class CreateSecurityRunRequest(BaseModel):
    """Request payload for creating a component security run."""

    target: ScanTarget
    profile: SecurityProfile = SecurityProfile.QUICK
    options: ScanOptions = Field(default_factory=ScanOptions)
    requested_by: str = ""
    session_id: str = ""
    release_candidate_id: str = ""
    execute_now: bool = True


@router.post("/runs", status_code=201, dependencies=[require_scope("component-security:write")])
async def create_run(body: CreateSecurityRunRequest, request: Request) -> dict[str, Any]:
    """Create a new component security run and optionally execute it immediately."""
    service = require_initialized_component_security_service(request)
    run = service.create_run(
        target=body.target,
        profile=body.profile,
        options=body.options,
        tenant_id=_tenant_id(request),
        requested_by=body.requested_by,
        session_id=body.session_id,
        release_candidate_id=body.release_candidate_id,
    )
    if body.execute_now:
        try:
            run = await service.launch_scan(run.id, tenant_id=_tenant_id(request))
        except SecurityScanError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return run.model_dump(mode="json")


@router.get("/runs", dependencies=[require_scope("component-security:read")])
async def list_runs(
    request: Request,
    status: RunStatus | None = None,
    profile: SecurityProfile | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List component security runs for current tenant."""
    tenant_id = _tenant_id(request)
    runs = require_initialized_component_security_service(request).list_runs(
        tenant_id=tenant_id if tenant_id else None,
        status=status,
        profile=profile,
        limit=limit,
    )
    return [run.model_dump(mode="json") for run in runs]


@router.get("/runs/{run_id}", dependencies=[require_scope("component-security:read")])
async def get_run(run_id: str, request: Request) -> dict[str, Any]:
    """Get component security run details by ID."""
    try:
        run = require_initialized_component_security_service(request).get_run(
            run_id,
            tenant_id=_tenant_id(request) or None,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return run.model_dump(mode="json")


@router.get("/runs/{run_id}/findings", dependencies=[require_scope("component-security:read")])
async def get_findings(
    run_id: str,
    request: Request,
    min_severity: FindingSeverity | None = None,
) -> dict[str, Any]:
    """Fetch findings for a run."""
    try:
        findings = require_initialized_component_security_service(request).fetch_findings(
            run_id,
            tenant_id=_tenant_id(request) or None,
            min_severity=min_severity,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "total_count": len(findings),
    }


@router.post("/runs/{run_id}/cancel", dependencies=[require_scope("component-security:write")])
async def cancel_run(run_id: str, request: Request) -> dict[str, Any]:
    """Cancel a running or pending run."""
    try:
        run = require_initialized_component_security_service(request).cancel_run(
            run_id,
            tenant_id=_tenant_id(request) or None,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return run.model_dump(mode="json")


@router.delete("/runs/{run_id}", dependencies=[require_scope("component-security:write")])
async def delete_run(run_id: str, request: Request) -> dict[str, str]:
    """Delete a run and associated findings."""
    try:
        require_initialized_component_security_service(request).delete_run(
            run_id,
            tenant_id=_tenant_id(request) or None,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": run_id}


@router.get("/runs/{run_id}/status", dependencies=[require_scope("component-security:read")])
async def get_run_status(run_id: str, request: Request) -> dict[str, str]:
    """Get status for polling clients."""
    try:
        run = require_initialized_component_security_service(request).get_run(
            run_id,
            tenant_id=_tenant_id(request) or None,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run_id": run.id, "status": run.status.value}


@router.get(
    "/runs/{run_id}/sarif",
    dependencies=[require_scope("component-security:read")],
)
async def get_run_sarif(run_id: str, request: Request) -> dict[str, Any]:
    """Export findings as SARIF 2.1.0 JSON."""
    service = require_initialized_component_security_service(request)
    try:
        sarif = service.sarif_export(
            run_id,
            tenant_id=_tenant_id(request) or None,
        )
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return sarif


# ---------------------------------------------------------------------------
# MCP security server management endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/mcp-servers",
    status_code=201,
    dependencies=[require_scope("component-security:write")],
)
async def register_mcp_server(body: dict[str, Any]) -> dict[str, Any]:
    """Register an MCP security server."""
    name = body.get("name", "")
    transport = body.get("transport", "")
    config = body.get("config", {})
    if not name or not transport:
        raise HTTPException(status_code=400, detail="name and transport are required")
    try:
        server = _mcp_scanner.register_server(name, transport, config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return server.model_dump(mode="json")


@router.get(
    "/mcp-servers",
    dependencies=[require_scope("component-security:read")],
)
async def list_mcp_servers() -> list[dict[str, Any]]:
    """List registered MCP security servers."""
    return [s.model_dump(mode="json") for s in _mcp_scanner.list_servers()]


@router.delete(
    "/mcp-servers/{name}",
    dependencies=[require_scope("component-security:write")],
)
async def remove_mcp_server(name: str) -> dict[str, str]:
    """Remove a registered MCP security server."""
    if not _mcp_scanner.unregister_server(name):
        raise HTTPException(status_code=404, detail=f"MCP server not found: {name}")
    return {"deleted": name}


# ---------------------------------------------------------------------------
# AI/LLM security scanning endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/llm-scan",
    dependencies=[require_scope("component-security:write")],
)
async def run_llm_scan(run_id: str, request: Request) -> dict[str, Any]:
    """Trigger AI-specific security scan for a run."""
    service = require_initialized_component_security_service(request)
    try:
        run = service.get_run(run_id, tenant_id=_tenant_id(request) or None)
    except RunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Run prompt injection scan on run metadata text fields
    findings: list[SecurityFinding] = []
    text_fields = [
        run.metadata.requested_by,
        run.metadata.session_id,
        run.target.repository_path,
        run.target.branch,
    ]
    for field in text_fields:
        if field:
            findings.extend(
                _llm_scanner.scan_prompt_safety(field, run_id=run.id, source="run_metadata")
            )

    # Model probes are materially slower than metadata scans, so keep them
    # aligned with the deepest security profile until runs capture an explicit
    # AI target model.
    default_model = resolve_default_model()
    if run.profile == SecurityProfile.DEEP and default_model:
        findings.extend(
            await asyncio.to_thread(
                _llm_scanner.scan_model_behavior,
                default_model,
                run_id=run.id,
            )
        )

    # Store findings alongside existing ones
    updated = service.add_findings(
        run.id,
        tenant_id=_tenant_id(request),
        findings=findings,
    )

    return {
        "run_id": run.id,
        "llm_findings": len(findings),
        "total_findings": updated.findings_count,
    }
