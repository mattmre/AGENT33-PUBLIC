"""FastAPI router for local skill pack management.

Provides 8 endpoints for listing, installing, uninstalling, enabling,
disabling, searching, and syncing skill packs.  All pack state changes
are tenant-scoped via the authenticated user's tenant_id.
"""

# NOTE: no ``from __future__ import annotations`` -- Pydantic needs these
# types at runtime for request-body validation.

from contextlib import suppress
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request

from agent33.packs.api_models import (
    EnableDisableResponse,
    EnablementMatrixResponse,
    EnablementMatrixUpdateRequest,
    InstallRequest,
    InstallResponse,
    PackDetail,
    PackRecoveryArchive,
    PackRecoveryDependent,
    PackRecoveryPreviewResponse,
    PackRollbackResponse,
    PackSkillInfo,
    PackSummary,
    PackTrustResponse,
    PackUpgradeRequest,
    TrustPolicyResponse,
    TrustPolicyUpdateRequest,
)
from agent33.packs.models import PackSource
from agent33.packs.outcome_pack import parse_outcome_pack_yaml
from agent33.packs.provenance import evaluate_trust
from agent33.packs.registry import PackRegistry
from agent33.security.permissions import require_scope
from agent33.workflows.definition import WorkflowDefinition

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/packs", tags=["packs"])


def _get_pack_registry(request: Request) -> PackRegistry | None:
    """Retrieve PackRegistry from app state.

    Returns None if not initialized (graceful degradation).
    """
    registry = getattr(request.app.state, "pack_registry", None)
    if isinstance(registry, PackRegistry):
        return registry
    return None


def _get_skill_registry(request: Request) -> Any:
    """Retrieve the skill registry from app state."""
    skill_registry = getattr(request.app.state, "skill_registry", None)
    if skill_registry is not None:
        return skill_registry

    pack_registry = _get_pack_registry(request)
    return getattr(pack_registry, "_skill_registry", None)


def _default_skill_provenance(pack: Any) -> str:
    """Return a fallback provenance label derived from pack metadata."""
    tags = set(getattr(pack, "tags", []) or [])
    if "evokore" in tags:
        return "imported-evokore"
    if "imported" in tags:
        return "imported-pack"
    return ""


def _get_pack_trust_manager(request: Request) -> Any:
    """Retrieve the pack trust manager from app state."""
    return getattr(request.app.state, "pack_trust_manager", None)


def _get_pack_rollback_manager(request: Request) -> Any:
    """Retrieve the pack rollback manager from app state."""
    return getattr(request.app.state, "pack_rollback_manager", None)


def _tenant_id(request: Request) -> str:
    """Extract tenant ID from authenticated principal."""
    user = getattr(request.state, "user", None)
    if user is None:
        return "default"
    return getattr(user, "tenant_id", None) or "default"


def _pack_to_summary(pack: Any) -> PackSummary:
    """Convert InstalledPack to PackSummary."""
    return PackSummary(
        name=pack.name,
        version=pack.version,
        description=pack.description,
        author=pack.author,
        tags=pack.tags,
        category=pack.category,
        skills_count=len(pack.loaded_skill_names),
        status=pack.status.value if hasattr(pack.status, "value") else str(pack.status),
    )


def _pack_to_detail(pack: Any, skill_registry: Any = None) -> PackDetail:
    """Convert InstalledPack to PackDetail."""
    skills: list[PackSkillInfo] = []
    for skill_info in pack.skills:
        loaded_skill = None
        if skill_registry is not None:
            loaded_skill = skill_registry.get(
                f"{pack.name}/{skill_info.name}"
            ) or skill_registry.get(skill_info.name)
        skills.append(
            PackSkillInfo(
                name=skill_info.name,
                path=skill_info.path,
                description=skill_info.description,
                category=getattr(loaded_skill, "category", "") or "",
                provenance=getattr(loaded_skill, "provenance", "")
                or _default_skill_provenance(pack),
                required=skill_info.required,
            )
        )
    return PackDetail(
        name=pack.name,
        version=pack.version,
        description=pack.description,
        author=pack.author,
        license=pack.license,
        tags=pack.tags,
        category=pack.category,
        skills=skills,
        loaded_skill_names=pack.loaded_skill_names,
        engine_min_version=pack.engine_min_version,
        installed_at=pack.installed_at,
        source=pack.source,
        source_reference=pack.source_reference,
        checksum=pack.checksum,
        status=pack.status.value if hasattr(pack.status, "value") else str(pack.status),
        provenance=pack.provenance,
    )


def _dependent_constraint(dependent: Any, dependency_name: str) -> str:
    """Return the declared version constraint a dependent has on a pack."""
    for dependency in getattr(dependent, "pack_dependencies", []) or []:
        if dependency.name == dependency_name:
            return str(getattr(dependency, "version_constraint", "") or "")
    return ""


def _recovery_recommendation(
    *,
    pack_name: str,
    target_version: str,
    dependents: list[PackRecoveryDependent],
    compatibility_errors: list[str],
    archived_versions: list[PackRecoveryArchive],
) -> tuple[str, list[str]]:
    """Build beginner-safe recovery guidance for destructive pack operations."""
    warnings: list[str] = []
    if dependents:
        warnings.append(
            f"Uninstall is blocked until {len(dependents)} dependent pack"
            f"{'' if len(dependents) == 1 else 's'} are removed or updated."
        )
    if compatibility_errors:
        warnings.append(
            "Selected upgrade target is not compatible with dependent pack requirements.",
        )
    if not archived_versions:
        warnings.append("No archived rollback revisions are available yet.")

    if compatibility_errors:
        return (
            f"Do not upgrade {pack_name} to {target_version} until compatibility "
            "errors are resolved.",
            warnings,
        )
    if dependents:
        return (
            f"Review dependent packs before uninstalling {pack_name}; compatible "
            "upgrades can proceed.",
            warnings,
        )
    if archived_versions:
        return (
            "No dependent packs are blocking this change, and rollback revisions "
            "are available if needed.",
            warnings,
        )
    return (
        "No dependent packs are blocking this change. Upgrade archives the "
        "current version before applying.",
        warnings,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", dependencies=[require_scope("agents:read")])
async def list_packs(request: Request) -> dict[str, Any]:
    """List all installed packs."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    packs = registry.list_installed()
    return {
        "packs": [_pack_to_summary(p).model_dump() for p in packs],
        "count": len(packs),
    }


@router.get("/enabled", dependencies=[require_scope("agents:read")])
async def list_enabled_packs(request: Request) -> dict[str, Any]:
    """List packs enabled for the current tenant."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    tenant = _tenant_id(request)
    packs = registry.list_enabled(tenant)
    return {
        "packs": [_pack_to_summary(p).model_dump() for p in packs],
        "count": len(packs),
        "tenant_id": tenant,
    }


@router.get("/search", dependencies=[require_scope("agents:read")])
async def search_packs(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
) -> dict[str, Any]:
    """Search installed packs by name, description, or tags."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    results = registry.search(q)
    return {
        "results": [_pack_to_summary(p).model_dump() for p in results],
        "count": len(results),
        "query": q,
    }


# ---------------------------------------------------------------------------
# Pack Hub endpoints (P-PACK v2)
#
# These routes use fixed prefix /hub/ and MUST be registered before the
# /{name} catch-all route so FastAPI matches them first.
# ---------------------------------------------------------------------------


def _get_pack_hub(request: Request) -> Any:
    """Retrieve PackHub from app state."""
    return getattr(request.app.state, "pack_hub", None)


@router.get("/hub/search", dependencies=[require_scope("agents:read")])
async def hub_search(
    request: Request,
    q: str = Query(..., min_length=1, description="Search query"),
    tags: str = Query(default="", description="Comma-separated tag filter"),
    limit: int = Query(default=10, ge=1, le=100, description="Max results"),
) -> dict[str, Any]:
    """Search the community pack registry."""
    hub = _get_pack_hub(request)
    if hub is None:
        raise HTTPException(status_code=503, detail="Pack hub not initialized")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = await hub.search(q, tags=tag_list, limit=limit)
    return {
        "results": [r.model_dump() for r in results],
        "count": len(results),
        "query": q,
    }


@router.get("/hub/entry/{name}", dependencies=[require_scope("agents:read")])
async def hub_get_entry(name: str, request: Request) -> dict[str, Any]:
    """Get a single pack entry from the community registry."""
    hub = _get_pack_hub(request)
    if hub is None:
        raise HTTPException(status_code=503, detail="Pack hub not initialized")

    entry = await hub.get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Pack '{name}' not found in registry")

    return {"entry": entry.model_dump()}


@router.get("/hub/revocation/{name}", dependencies=[require_scope("agents:read")])
async def hub_get_revocation_status(
    name: str,
    request: Request,
    version: str = Query(default="", description="Pack version to check (empty = any)"),
) -> dict[str, Any]:
    """Return the revocation status for a named pack from the community registry.

    Checks both the per-entry ``revoked`` flag on ``PackHubEntry`` and the
    registry-level ``revoked`` list in ``PackRegistryPayload``.  A revoked
    pack must be rejected during install.
    """
    hub = _get_pack_hub(request)
    if hub is None:
        raise HTTPException(status_code=503, detail="Pack hub not initialized")

    status = await hub.get_revocation_status(name, version)
    result: dict[str, Any] = status.model_dump()
    return result


# ---------------------------------------------------------------------------
# Pack health & audit endpoints (Phase 33 / S24)
#
# These routes use fixed prefixes (/health, /audit, /compliance) and MUST
# be registered before the /{name} catch-all route so FastAPI matches them
# first.
# ---------------------------------------------------------------------------


def _get_pack_audit(request: Request) -> Any:
    """Retrieve PackAuditService from app state."""
    return getattr(request.app.state, "pack_audit", None)


@router.get("/health", dependencies=[require_scope("agents:read")])
async def get_pack_health_summary(request: Request) -> dict[str, Any]:
    """Return aggregate health metrics for all installed packs."""
    svc = _get_pack_audit(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Pack audit service not initialized")
    summary = svc.check_all_health()
    result: dict[str, Any] = summary.model_dump(mode="json")
    return result


@router.get("/health/details", dependencies=[require_scope("agents:read")])
async def get_pack_health_details(request: Request) -> dict[str, Any]:
    """Return per-pack health check details for all installed packs."""
    svc = _get_pack_audit(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Pack audit service not initialized")
    details = svc.get_health_details()
    return {
        "details": [d.model_dump(mode="json") for d in details],
        "count": len(details),
    }


@router.get("/health/{name}", dependencies=[require_scope("agents:read")])
async def get_pack_health(name: str, request: Request) -> dict[str, Any]:
    """Return health check result for a single pack."""
    svc = _get_pack_audit(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Pack audit service not initialized")
    try:
        check = svc.check_pack_health(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result: dict[str, Any] = check.model_dump(mode="json")
    return result


@router.get("/audit", dependencies=[require_scope("agents:read")])
async def get_audit_log(
    request: Request,
    pack_name: str = Query(default="", description="Filter by pack name"),
    event_type: str = Query(default="", description="Filter by event type"),
    limit: int = Query(default=50, ge=1, le=500, description="Max events to return"),
) -> dict[str, Any]:
    """Return pack audit log with optional filters."""
    svc = _get_pack_audit(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Pack audit service not initialized")
    events = svc.get_audit_log(
        pack_name=pack_name or None,
        event_type=event_type or None,
        limit=limit,
    )
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "count": len(events),
    }


@router.get("/audit/{name}", dependencies=[require_scope("agents:read")])
async def get_pack_audit_log(
    name: str,
    request: Request,
    event_type: str = Query(default="", description="Filter by event type"),
    limit: int = Query(default=50, ge=1, le=500, description="Max events to return"),
) -> dict[str, Any]:
    """Return audit log filtered to a specific pack."""
    svc = _get_pack_audit(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Pack audit service not initialized")
    events = svc.get_audit_log(
        pack_name=name,
        event_type=event_type or None,
        limit=limit,
    )
    return {
        "events": [e.model_dump(mode="json") for e in events],
        "count": len(events),
    }


@router.get("/compliance/{name}", dependencies=[require_scope("agents:read")])
async def get_pack_compliance(name: str, request: Request) -> dict[str, Any]:
    """Return compliance report for a single pack."""
    svc = _get_pack_audit(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Pack audit service not initialized")
    try:
        report = svc.compliance_check(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result: dict[str, Any] = report.model_dump(mode="json")
    return result


@router.post("/compliance/check-all", dependencies=[require_scope("admin")])
async def check_all_compliance(request: Request) -> dict[str, Any]:
    """Batch compliance check for all installed packs."""
    svc = _get_pack_audit(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Pack audit service not initialized")
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    packs = registry.list_installed()
    reports = []
    for pack in packs:
        try:
            report = svc.compliance_check(pack.name)
            reports.append(report.model_dump(mode="json"))
        except Exception:
            logger.warning("compliance_check_failed", pack_name=pack.name, exc_info=True)

    compliant_count = sum(1 for r in reports if r.get("compliant"))
    return {
        "reports": reports,
        "count": len(reports),
        "compliant": compliant_count,
        "non_compliant": len(reports) - compliant_count,
    }


# ---------------------------------------------------------------------------
# Dry-run simulation (P-PACK v1)
# ---------------------------------------------------------------------------


@router.get("/{name}/dry-run", dependencies=[require_scope("agents:read")])
async def dry_run_pack(
    name: str,
    request: Request,
    agent: str = Query(default="", description="Target agent name"),
    session: str = Query(default="", description="Target session ID"),
) -> dict[str, object]:
    """Preview what would change if this pack were applied.

    Returns a simulation of prompt addenda, tool config, and skills that
    would be loaded -- without modifying any state.
    """
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    try:
        result = registry.dry_run(name, agent_name=agent, session_id=session)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return result


@router.get(
    "/{name}/recovery-preview",
    response_model=PackRecoveryPreviewResponse,
    dependencies=[require_scope("agents:read")],
)
async def get_pack_recovery_preview(
    name: str,
    request: Request,
    target_version: str = Query(default="", description="Optional upgrade target version"),
) -> PackRecoveryPreviewResponse:
    """Preview dependency impact and rollback options before destructive pack changes."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    pack = registry.get(name)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Pack '{name}' not found")

    dependents = [
        PackRecoveryDependent(
            name=dependent.name,
            version=dependent.version,
            version_constraint=_dependent_constraint(dependent, name),
            status=dependent.status.value
            if hasattr(dependent.status, "value")
            else str(dependent.status),
        )
        for dependent in registry.find_dependents(name)
    ]

    compatibility_errors: list[str] = []
    if target_version and target_version != pack.version:
        compatibility_errors = registry.check_dependents_compatible(name, target_version)

    rollback_manager = _get_pack_rollback_manager(request)
    archived_versions: list[PackRecoveryArchive] = []
    if rollback_manager is not None:
        archived_versions = [
            PackRecoveryArchive(version=revision.version, archived_at=revision.archived_at)
            for revision in rollback_manager.list_archived_versions(name)
        ]

    recommended_action, warnings = _recovery_recommendation(
        pack_name=name,
        target_version=target_version or pack.version,
        dependents=dependents,
        compatibility_errors=compatibility_errors,
        archived_versions=archived_versions,
    )

    return PackRecoveryPreviewResponse(
        pack_name=name,
        installed_version=pack.version,
        target_version=target_version,
        affected_skills=pack.loaded_skill_names,
        enabled_tenants=registry.enabled_tenants(name),
        dependents=dependents,
        compatibility_errors=compatibility_errors,
        archived_versions=archived_versions,
        can_uninstall_safely=len(dependents) == 0,
        can_upgrade_safely=len(compatibility_errors) == 0,
        can_rollback=len(archived_versions) > 0,
        recommended_action=recommended_action,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Session-scoped enable/disable (P-PACK v1)
# ---------------------------------------------------------------------------


@router.post("/{name}/enable-session", dependencies=[require_scope("agents:write")])
async def enable_pack_for_session(
    name: str,
    request: Request,
    session_id: str = Query(..., min_length=1, description="Session ID"),
) -> dict[str, Any]:
    """Enable a pack for a specific session (session-scoped, not tenant-wide)."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    try:
        registry.enable_for_session(name, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "success": True,
        "pack_name": name,
        "session_id": session_id,
        "action": "enabled_for_session",
    }


@router.post("/{name}/disable-session", dependencies=[require_scope("agents:write")])
async def disable_pack_for_session(
    name: str,
    request: Request,
    session_id: str = Query(..., min_length=1, description="Session ID"),
) -> dict[str, Any]:
    """Disable a pack for a specific session."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    try:
        registry.disable_for_session(name, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "success": True,
        "pack_name": name,
        "session_id": session_id,
        "action": "disabled_for_session",
    }


# ---------------------------------------------------------------------------
# Outcome pack manifests
# ---------------------------------------------------------------------------


@router.get("/{name}/outcome-manifests", dependencies=[require_scope("agents:read")])
async def get_pack_outcome_manifests(name: str, request: Request) -> dict[str, Any]:
    """Return validated outcome manifests and workflows bundled with an installed pack."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    pack = registry.get(name)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Pack '{name}' not found")

    pack_dir = pack.pack_dir.resolve()
    results: list[dict[str, Any]] = []
    for entry in pack.outcome_packs:
        manifest_path = (pack_dir / entry.path).resolve()
        try:
            manifest_path.relative_to(pack_dir)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Outcome pack path '{entry.path}' escapes pack directory",
            ) from exc

        try:
            manifest = parse_outcome_pack_yaml(manifest_path)
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to load outcome pack '{entry.path}': {exc}",
            ) from exc

        workflows: list[dict[str, Any]] = []
        for workflow_ref in manifest.workflows:
            if workflow_ref.definition is not None:
                workflows.append(workflow_ref.definition.model_dump(mode="json"))
                continue
            if workflow_ref.path is None:
                continue
            workflow_path = (pack_dir / workflow_ref.path).resolve()
            try:
                workflow_path.relative_to(pack_dir)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Workflow path '{workflow_ref.path}' escapes pack directory",
                ) from exc
            try:
                workflow = WorkflowDefinition.load_from_file(workflow_path)
            except (FileNotFoundError, ValueError, ImportError) as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to load workflow '{workflow_ref.path}': {exc}",
                ) from exc
            workflows.append(workflow.model_dump(mode="json"))

        results.append(
            {
                "entry": entry.model_dump(mode="json"),
                "manifest": manifest.model_dump(mode="json"),
                "workflows": workflows,
            }
        )

    return {"packs": results, "count": len(results)}


# ---------------------------------------------------------------------------
# Single-pack detail (catch-all /{name} — must come after fixed paths above)
# ---------------------------------------------------------------------------


@router.get("/{name}", dependencies=[require_scope("agents:read")])
async def get_pack(name: str, request: Request) -> dict[str, Any]:
    """Get details of an installed pack."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    pack = registry.get(name)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Pack '{name}' not found")

    tenant = _tenant_id(request)
    detail = _pack_to_detail(pack, _get_skill_registry(request))
    return {
        **detail.model_dump(mode="json"),
        "enabled_for_tenant": registry.is_enabled(name, tenant),
    }


@router.post("/install", status_code=201, dependencies=[require_scope("agents:write")])
async def install_pack(body: InstallRequest, request: Request) -> dict[str, Any]:
    """Install a pack from a local path."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    source = PackSource(
        source_type=body.source_type,
        path=body.path,
        name=body.name,
        version=body.version,
    )

    result = registry.install(source)
    response = InstallResponse(
        success=result.success,
        pack_name=result.pack_name,
        version=result.version,
        skills_loaded=result.skills_loaded,
        errors=result.errors,
        warnings=result.warnings,
    )

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Failed to install pack '{result.pack_name}'",
                "errors": result.errors,
            },
        )

    return response.model_dump()


@router.post("/{name}/upgrade", dependencies=[require_scope("agents:write")])
async def upgrade_pack(
    name: str,
    body: PackUpgradeRequest,
    request: Request,
) -> dict[str, Any]:
    """Upgrade an installed pack from a local or marketplace source."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")
    rollback_manager = _get_pack_rollback_manager(request)
    if rollback_manager is not None:
        try:
            with suppress(ValueError):
                rollback_manager.archive_current(name)
        except OSError as exc:
            logger.warning(
                "pack_upgrade_archive_failed",
                pack_name=name,
                error=str(exc),
            )

    source = PackSource(
        source_type=body.source_type,
        path=body.path,
        name=body.name or name,
        version=body.version,
    )
    result = registry.upgrade_from_source(name, source)
    response = InstallResponse(
        success=result.success,
        pack_name=result.pack_name,
        version=result.version,
        skills_loaded=result.skills_loaded,
        errors=result.errors,
        warnings=result.warnings,
    )
    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Failed to upgrade pack '{name}'",
                "errors": result.errors,
            },
        )
    return response.model_dump()


@router.delete(
    "/{name}",
    status_code=204,
    response_model=None,
    dependencies=[require_scope("agents:write")],
)
async def uninstall_pack(name: str, request: Request) -> None:
    """Uninstall a pack and remove its skills."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    try:
        registry.uninstall(name)
    except ValueError as exc:
        if "not installed" in str(exc):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if "required by" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{name}/enable", dependencies=[require_scope("agents:write")])
async def enable_pack(name: str, request: Request) -> dict[str, Any]:
    """Enable a pack for the current tenant."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    tenant = _tenant_id(request)
    try:
        registry.enable(name, tenant)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return EnableDisableResponse(
        success=True,
        pack_name=name,
        tenant_id=tenant,
        action="enabled",
    ).model_dump()


@router.post("/{name}/disable", dependencies=[require_scope("agents:write")])
async def disable_pack(name: str, request: Request) -> dict[str, Any]:
    """Disable a pack for the current tenant."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    tenant = _tenant_id(request)
    try:
        registry.disable(name, tenant)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return EnableDisableResponse(
        success=True,
        pack_name=name,
        tenant_id=tenant,
        action="disabled",
    ).model_dump()


@router.post("/{name}/sync", dependencies=[require_scope("agents:write")])
async def sync_pack(name: str, request: Request) -> dict[str, Any]:
    """Re-scan and reload a pack from disk.

    Useful after editing pack skills on the filesystem.
    """
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")

    pack = registry.get(name)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Pack '{name}' not found")

    result = registry.upgrade(name, pack.pack_dir)
    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Failed to sync pack '{name}'",
                "errors": result.errors,
            },
        )

    return {
        "success": True,
        "pack_name": name,
        "version": result.version,
        "skills_loaded": result.skills_loaded,
    }


@router.get(
    "/{name}/trust",
    response_model=PackTrustResponse,
    dependencies=[require_scope("agents:read")],
)
async def get_pack_trust(name: str, request: Request) -> PackTrustResponse:
    """Return provenance and policy evaluation for one installed pack."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")
    pack = registry.get(name)
    if pack is None:
        raise HTTPException(status_code=404, detail=f"Pack '{name}' not found")

    policy = registry.trust_policy
    decision = evaluate_trust(pack.provenance, policy)
    return PackTrustResponse(
        pack_name=pack.name,
        installed_version=pack.version,
        source=pack.source,
        source_reference=pack.source_reference,
        provenance=pack.provenance,
        policy=policy,
        allowed=decision.allowed,
        reason=decision.reason,
    )


@router.get(
    "/trust/policy",
    response_model=TrustPolicyResponse,
    dependencies=[require_scope("agents:read")],
)
async def get_pack_trust_policy(request: Request) -> TrustPolicyResponse:
    """Return the active trust policy for pack installation."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")
    return TrustPolicyResponse(policy=registry.trust_policy)


@router.put(
    "/trust/policy",
    response_model=TrustPolicyResponse,
    dependencies=[require_scope("admin")],
)
async def update_pack_trust_policy(
    body: TrustPolicyUpdateRequest,
    request: Request,
) -> TrustPolicyResponse:
    """Update the active trust policy for pack installation."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")
    manager = _get_pack_trust_manager(request)
    if manager is None:
        raise HTTPException(status_code=503, detail="Pack trust manager not initialized")
    policy = manager.update_policy(
        require_signature=body.require_signature,
        min_trust_level=body.min_trust_level,
        allowed_signers=body.allowed_signers,
    )
    registry.set_trust_policy(policy)
    return TrustPolicyResponse(policy=policy)


@router.get(
    "/enablement/matrix",
    response_model=EnablementMatrixResponse,
    dependencies=[require_scope("admin")],
)
async def get_enablement_matrix(request: Request) -> EnablementMatrixResponse:
    """Return operator-visible pack enablement state across tenants."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")
    matrix = registry.get_enablement_matrix()
    return EnablementMatrixResponse(
        packs=sorted(matrix),
        tenants=sorted({tenant for tenant_map in matrix.values() for tenant in tenant_map}),
        matrix=matrix,
    )


@router.put(
    "/enablement/matrix",
    response_model=EnablementMatrixResponse,
    dependencies=[require_scope("admin")],
)
async def update_enablement_matrix(
    body: EnablementMatrixUpdateRequest,
    request: Request,
) -> EnablementMatrixResponse:
    """Apply operator-managed enablement changes across tenants."""
    registry = _get_pack_registry(request)
    if registry is None:
        raise HTTPException(status_code=503, detail="Pack registry not initialized")
    try:
        registry.apply_enablement_matrix(body.matrix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    matrix = registry.get_enablement_matrix()
    return EnablementMatrixResponse(
        packs=sorted(matrix),
        tenants=sorted({tenant for tenant_map in matrix.values() for tenant in tenant_map}),
        matrix=matrix,
    )


@router.post(
    "/{name}/rollback",
    response_model=PackRollbackResponse,
    dependencies=[require_scope("agents:write")],
)
async def rollback_pack(
    name: str,
    request: Request,
    version: str = Query(default=""),
) -> PackRollbackResponse:
    """Rollback an installed pack to an archived revision."""
    manager = _get_pack_rollback_manager(request)
    if manager is None:
        raise HTTPException(status_code=503, detail="Pack rollback manager not initialized")
    try:
        result, revision = manager.rollback(name, version=version)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.success:
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"Failed to rollback pack '{name}'",
                "errors": result.errors,
            },
        )
    return PackRollbackResponse(
        success=True,
        pack_name=name,
        version=result.version,
        restored_from_version=revision.version,
        errors=[],
    )


# ---------------------------------------------------------------------------
# Trust dashboard endpoints (Phase 33 / S23)
# ---------------------------------------------------------------------------


def _get_trust_analytics(request: Request) -> Any:
    """Retrieve TrustAnalyticsService from app state."""
    return getattr(request.app.state, "trust_analytics", None)


@router.get("/trust/dashboard", dependencies=[require_scope("agents:read")])
async def get_trust_dashboard(request: Request) -> dict[str, Any]:
    """Return the full trust dashboard: overview, chain, audit, policy, curation."""
    svc = _get_trust_analytics(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Trust analytics service not initialized")
    summary = svc.get_dashboard()
    result: dict[str, Any] = summary.model_dump(mode="json")
    return result


@router.get("/trust/overview", dependencies=[require_scope("agents:read")])
async def get_trust_overview(request: Request) -> dict[str, Any]:
    """Return aggregate trust metrics for all installed packs."""
    svc = _get_trust_analytics(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Trust analytics service not initialized")
    overview = svc.get_overview()
    result: dict[str, Any] = overview.model_dump(mode="json")
    return result


@router.get("/trust/chain", dependencies=[require_scope("agents:read")])
async def get_trust_chain(request: Request) -> dict[str, Any]:
    """Return trust chain entries for all installed packs."""
    svc = _get_trust_analytics(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Trust analytics service not initialized")
    chain = svc.get_trust_chain()
    return {
        "entries": [entry.model_dump(mode="json") for entry in chain],
        "count": len(chain),
    }


@router.get("/trust/audit", dependencies=[require_scope("agents:read")])
async def get_trust_audit(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500, description="Max audit records to return"),
) -> dict[str, Any]:
    """Return recent trust-related audit trail records."""
    svc = _get_trust_analytics(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Trust analytics service not initialized")
    records = svc.get_audit_trail(limit=limit)
    return {
        "records": [r.model_dump(mode="json") for r in records],
        "count": len(records),
    }


@router.post("/trust/verify-all", dependencies=[require_scope("admin")])
async def verify_all_signatures(request: Request) -> dict[str, Any]:
    """Batch-verify signatures for all signed packs."""
    svc = _get_trust_analytics(request)
    if svc is None:
        raise HTTPException(status_code=503, detail="Trust analytics service not initialized")
    results = svc.verify_all_signatures()
    return {
        "results": results,
        "total_verified": len(results),
        "all_valid": all(r.get("valid") is True for r in results) if results else True,
    }
