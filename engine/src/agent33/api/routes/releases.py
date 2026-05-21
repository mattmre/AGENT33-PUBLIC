"""FastAPI router for release automation, sync, and rollback."""

# NOTE: no ``from __future__ import annotations`` — Pydantic needs these
# types at runtime for request-body validation.

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent33.component_security.models import FindingsSummary, SecurityGatePolicy
from agent33.release.models import (
    CheckStatus,
    ReleaseStatus,
    ReleaseType,
    RollbackType,
    SyncFrequency,
    SyncStrategy,
    SyncTransform,
)
from agent33.release.service import (
    InvalidReleaseTransitionError,
    ReleaseNotFoundError,
    ReleaseService,
)
from agent33.security.permissions import require_scope

logger = structlog.get_logger()

router = APIRouter(prefix="/v1/releases", tags=["releases"])

# Singleton service
_service = ReleaseService()


def set_release_service(service: ReleaseService) -> None:
    """Inject a shared release service instance (called from lifespan)."""
    global _service  # noqa: PLW0603
    _service = service


def get_release_service() -> ReleaseService:
    """Return the release service singleton (for testing injection)."""
    return _service


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateReleaseRequest(BaseModel):
    version: str
    release_type: ReleaseType = ReleaseType.MINOR
    description: str = ""


class TransitionRequest(BaseModel):
    to_status: ReleaseStatus


class CutRCRequest(BaseModel):
    rc_version: str = ""


class PublishRequest(BaseModel):
    released_by: str = ""


class UpdateCheckRequest(BaseModel):
    check_id: str
    status: CheckStatus
    message: str = ""


class SecurityGateEvaluationRequest(BaseModel):
    run_id: str
    summary: FindingsSummary
    policy: SecurityGatePolicy | None = None


class CreateSyncRuleRequest(BaseModel):
    source_pattern: str = "core/**/*.md"
    target_repo: str = ""
    target_path: str = ""
    strategy: SyncStrategy = SyncStrategy.COPY
    frequency: SyncFrequency = SyncFrequency.ON_RELEASE
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    transforms: list[SyncTransform] = Field(default_factory=list)


class DryRunRequest(BaseModel):
    available_files: list[str] = Field(default_factory=list)
    release_version: str = ""


class ExecuteSyncRequest(BaseModel):
    available_files: list[str] = Field(default_factory=list)
    release_version: str = ""


class InitiateRollbackRequest(BaseModel):
    reason: str
    rollback_type: RollbackType = RollbackType.PLANNED
    target_version: str = ""
    initiated_by: str = ""


class RecommendRollbackRequest(BaseModel):
    severity: str
    impact: str


# ---------------------------------------------------------------------------
# Release CRUD routes
# ---------------------------------------------------------------------------


@router.post(
    "",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def create_release(body: CreateReleaseRequest) -> dict[str, Any]:
    """Create a new release."""
    release = _service.create_release(
        version=body.version,
        release_type=body.release_type,
        description=body.description,
    )
    return {
        "release_id": release.release_id,
        "version": release.version,
        "status": release.status.value,
        "checklist_items": len(release.evidence.checklist),
    }


@router.get(
    "",
    dependencies=[require_scope("workflows:read")],
)
async def list_releases(
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List releases."""
    status_filter = ReleaseStatus(status) if status else None
    releases = _service.list_releases(status=status_filter, limit=limit)
    return [
        {
            "release_id": r.release_id,
            "version": r.version,
            "status": r.status.value,
            "release_type": r.release_type.value,
            "created_at": r.created_at.isoformat(),
        }
        for r in releases
    ]


@router.get(
    "/{release_id}",
    dependencies=[require_scope("workflows:read")],
)
async def get_release(release_id: str) -> dict[str, Any]:
    """Get release details."""
    try:
        release = _service.get_release(release_id)
    except ReleaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Release not found: {release_id}") from None
    return release.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Lifecycle routes
# ---------------------------------------------------------------------------


@router.post(
    "/{release_id}/freeze",
    dependencies=[require_scope("tools:execute")],
)
async def freeze_release(release_id: str) -> dict[str, Any]:
    """Freeze a release (no more features)."""
    try:
        release = _service.freeze(release_id)
    except ReleaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Release not found: {release_id}") from None
    except InvalidReleaseTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"release_id": release.release_id, "status": release.status.value}


@router.post(
    "/{release_id}/rc",
    dependencies=[require_scope("tools:execute")],
)
async def cut_rc(release_id: str, body: CutRCRequest) -> dict[str, Any]:
    """Cut a release candidate."""
    try:
        release = _service.cut_rc(release_id, rc_version=body.rc_version)
    except ReleaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Release not found: {release_id}") from None
    except InvalidReleaseTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"release_id": release.release_id, "status": release.status.value}


@router.post(
    "/{release_id}/validate",
    dependencies=[require_scope("tools:execute")],
)
async def start_validation(release_id: str) -> dict[str, Any]:
    """Start validation of a release candidate."""
    try:
        release = _service.start_validation(release_id)
    except ReleaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Release not found: {release_id}") from None
    except InvalidReleaseTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {"release_id": release.release_id, "status": release.status.value}


@router.post(
    "/{release_id}/publish",
    dependencies=[require_scope("tools:execute")],
)
async def publish_release(release_id: str, body: PublishRequest) -> dict[str, Any]:
    """Publish a release (checklist must pass)."""
    try:
        release = _service.publish(release_id, released_by=body.released_by)
    except ReleaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Release not found: {release_id}") from None
    except InvalidReleaseTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return {
        "release_id": release.release_id,
        "status": release.status.value,
        "version": release.version,
    }


# ---------------------------------------------------------------------------
# Checklist routes
# ---------------------------------------------------------------------------


@router.get(
    "/{release_id}/checklist",
    dependencies=[require_scope("workflows:read")],
)
async def get_checklist(release_id: str) -> dict[str, Any]:
    """Get the release checklist."""
    try:
        release = _service.get_release(release_id)
    except ReleaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Release not found: {release_id}") from None
    passed, failures = _service.evaluate_checklist(release_id)
    return {
        "release_id": release_id,
        "passed": passed,
        "failures": failures,
        "checks": [c.model_dump() for c in release.evidence.checklist],
    }


@router.patch(
    "/{release_id}/checklist",
    dependencies=[require_scope("tools:execute")],
)
async def update_check(release_id: str, body: UpdateCheckRequest) -> dict[str, Any]:
    """Update a checklist item status."""
    try:
        _service.update_check(release_id, body.check_id, body.status, body.message)
    except ReleaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Release not found: {release_id}") from None
    return {"release_id": release_id, "check_id": body.check_id, "status": body.status.value}


@router.post(
    "/{release_id}/security-gate",
    dependencies=[require_scope("tools:execute")],
)
async def apply_security_gate(
    release_id: str,
    body: SecurityGateEvaluationRequest,
) -> dict[str, Any]:
    """Apply RL-06 gate status from component security summary."""
    try:
        result = _service.apply_component_security_gate(
            release_id,
            run_id=body.run_id,
            summary=body.summary,
            policy=body.policy,
        )
    except ReleaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Release not found: {release_id}") from None
    return {
        "release_id": release_id,
        "run_id": result.run_id,
        "decision": result.decision.value,
        "message": result.message,
        "summary": result.summary.model_dump(),
    }


# ---------------------------------------------------------------------------
# Sync routes
# ---------------------------------------------------------------------------


@router.post(
    "/sync/rules",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def create_sync_rule(body: CreateSyncRuleRequest) -> dict[str, Any]:
    """Create a sync rule."""
    from agent33.release.models import SyncRule

    rule = SyncRule(
        source_pattern=body.source_pattern,
        target_repo=body.target_repo,
        target_path=body.target_path,
        strategy=body.strategy,
        frequency=body.frequency,
        include_patterns=body.include_patterns,
        exclude_patterns=body.exclude_patterns,
        transforms=body.transforms,
    )
    result = _service.add_sync_rule(rule)
    return {"rule_id": result.rule_id, "target_repo": result.target_repo}


@router.get(
    "/sync/rules",
    dependencies=[require_scope("workflows:read")],
)
async def list_sync_rules() -> list[dict[str, Any]]:
    """List sync rules."""
    rules = _service.list_sync_rules()
    return [r.model_dump(mode="json") for r in rules]


@router.post(
    "/sync/rules/{rule_id}/dry-run",
    dependencies=[require_scope("tools:execute")],
)
async def sync_dry_run(rule_id: str, body: DryRunRequest) -> dict[str, Any]:
    """Execute a dry-run sync."""
    exe = _service.sync_engine.dry_run(
        rule_id=rule_id,
        available_files=body.available_files,
        release_version=body.release_version,
    )
    return {
        "execution_id": exe.execution_id,
        "status": exe.status.value,
        "files_added": exe.files_added,
        "dry_run": exe.dry_run,
        "errors": exe.errors,
    }


@router.post(
    "/sync/rules/{rule_id}/execute",
    dependencies=[require_scope("tools:execute")],
)
async def sync_execute(rule_id: str, body: ExecuteSyncRequest) -> dict[str, Any]:
    """Execute a real sync."""
    exe = _service.sync_engine.execute(
        rule_id=rule_id,
        available_files=body.available_files,
        release_version=body.release_version,
    )
    return {
        "execution_id": exe.execution_id,
        "status": exe.status.value,
        "files_added": exe.files_added,
        "dry_run": exe.dry_run,
        "errors": exe.errors,
    }


# ---------------------------------------------------------------------------
# Rollback routes
# ---------------------------------------------------------------------------


@router.post(
    "/{release_id}/rollback",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def initiate_rollback(release_id: str, body: InitiateRollbackRequest) -> dict[str, Any]:
    """Initiate a rollback for a release."""
    try:
        release = _service.initiate_rollback(
            release_id=release_id,
            reason=body.reason,
            rollback_type=body.rollback_type,
            target_version=body.target_version,
            initiated_by=body.initiated_by,
        )
    except ReleaseNotFoundError:
        raise HTTPException(status_code=404, detail=f"Release not found: {release_id}") from None
    rollbacks = _service.rollback_manager.list_all(release_id=release_id, limit=1)
    rollback_id = rollbacks[0].rollback_id if rollbacks else ""
    return {
        "release_id": release.release_id,
        "status": release.status.value,
        "rollback_id": rollback_id,
    }


@router.get(
    "/rollbacks",
    dependencies=[require_scope("workflows:read")],
)
async def list_rollbacks(
    release_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List rollback records."""
    records = _service.rollback_manager.list_all(release_id=release_id, limit=limit)
    return [r.model_dump(mode="json") for r in records]


@router.post(
    "/rollback/recommend",
    dependencies=[require_scope("workflows:read")],
)
async def recommend_rollback(
    body: RecommendRollbackRequest,
) -> dict[str, str]:
    """Get a rollback recommendation based on severity and impact."""
    rollback_type, approval = _service.rollback_manager.recommend(body.severity, body.impact)
    return {
        "rollback_type": rollback_type.value,
        "approval_level": approval,
    }
