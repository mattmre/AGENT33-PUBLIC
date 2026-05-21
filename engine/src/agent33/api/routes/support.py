"""FastAPI router for support diagnostics and bundle generation."""

from __future__ import annotations

from fastapi import APIRouter

from agent33.security.permissions import require_scope
from agent33.support.bundles import (
    SupportBundleManifest,
    SupportBundleRequest,
    build_support_bundle_manifest,
)
from agent33.support.diagnostics import (
    SetupDiagnosticCheck,
    SetupDiagnosticReport,
    build_setup_diagnostic_report,
)

router = APIRouter(prefix="/v1/support", tags=["support"])


@router.post("/diagnostics", dependencies=[require_scope("admin:read")])
async def run_setup_diagnostics(
    checks: list[SetupDiagnosticCheck],
) -> SetupDiagnosticReport:
    """Run setup diagnostics and return a consolidated report."""
    return build_setup_diagnostic_report(checks)


@router.post(
    "/bundles",
    dependencies=[require_scope("admin:read")],
    status_code=201,
)
async def create_support_bundle(request: SupportBundleRequest) -> SupportBundleManifest:
    """Generate a support bundle manifest from the given request."""
    return build_support_bundle_manifest(request)
