"""FastAPI router for synthetic environment generation (AWM Tier 2 A5)."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from agent33.evaluation.synthetic_envs.service import SyntheticEnvironmentService
from agent33.security.permissions import require_scope

router = APIRouter(
    prefix="/v1/evaluation/synthetic-environments",
    tags=["synthetic-environments"],
)

_service: SyntheticEnvironmentService | None = None


def set_synthetic_environment_service(service: SyntheticEnvironmentService) -> None:
    """Inject the synthetic environment service during app startup."""
    global _service  # noqa: PLW0603
    _service = service


def get_synthetic_environment_service() -> SyntheticEnvironmentService:
    """Return the service singleton, raising 503 if not initialized."""
    if _service is None:
        raise HTTPException(
            status_code=503,
            detail="Synthetic environment service not initialized",
        )
    return _service


class GenerateBundleRequest(BaseModel):
    workflow_names: list[str] = Field(default_factory=list, max_length=25)
    variations_per_workflow: int = Field(default=1, ge=1, le=20)


@router.get(
    "/workflows",
    dependencies=[require_scope("workflows:read")],
)
async def list_workflows() -> list[dict[str, Any]]:
    """List workflow templates available for synthetic generation."""
    service = get_synthetic_environment_service()
    return [entry.model_dump(mode="json") for entry in service.list_workflows()]


@router.post(
    "/bundles",
    status_code=201,
    dependencies=[require_scope("tools:execute")],
)
async def generate_bundle(body: GenerateBundleRequest) -> dict[str, Any]:
    """Generate a synthetic environment bundle."""
    service = get_synthetic_environment_service()
    try:
        bundle = service.generate_bundle(
            workflow_names=body.workflow_names or None,
            variations_per_workflow=body.variations_per_workflow,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return bundle.model_dump(mode="json")


@router.get(
    "/bundles/{bundle_id}",
    dependencies=[require_scope("workflows:read")],
)
async def get_bundle(bundle_id: str) -> dict[str, Any]:
    """Retrieve a previously generated bundle."""
    service = get_synthetic_environment_service()
    bundle = service.get_bundle(bundle_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail=f"Bundle not found: {bundle_id}")
    return bundle.model_dump(mode="json")
