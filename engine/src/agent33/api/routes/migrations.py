"""FastAPI routes for Alembic migration status inspection."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from agent33.migrations.checker import MigrationChecker, MigrationStatus
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/migrations", tags=["migrations"])


def get_migration_checker(request: Request) -> MigrationChecker:
    """Return the app-scoped migration checker."""
    checker: MigrationChecker | None = getattr(request.app.state, "migration_checker", None)
    if checker is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Migration checker not initialized",
        )
    return checker


MigrationCheckerDep = Annotated[MigrationChecker, Depends(get_migration_checker)]


@router.get(
    "/status",
    response_model=MigrationStatus,
    dependencies=[require_scope("admin")],
)
async def migration_status(checker: MigrationCheckerDep) -> MigrationStatus:
    """Return the current Alembic migration chain status (offline)."""
    return checker.get_status()


@router.get(
    "/revisions",
    dependencies=[require_scope("admin")],
)
async def list_revisions(checker: MigrationCheckerDep) -> dict[str, Any]:
    """List all discovered Alembic migration revisions with metadata."""
    revisions = checker.list_revisions()
    return {"count": len(revisions), "revisions": revisions}
