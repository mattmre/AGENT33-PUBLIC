"""Execution subsystem API routes (GPU info, adapter status)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from agent33.config import settings
from agent33.execution.gpu import GPUDockerManager
from agent33.security.permissions import require_scope

router = APIRouter(prefix="/v1/execution", tags=["execution"])


@router.get(
    "/gpu-info",
    dependencies=[require_scope("agents:read")],
)
async def gpu_info(request: Request) -> dict[str, Any]:
    """Return GPU availability, runtime, and device information.

    When ``execution_gpu_enabled`` is ``False`` the endpoint still returns
    the detection result but marks the feature as disabled so callers know
    GPU workloads will not be dispatched.
    """
    gpu_manager: GPUDockerManager | None = getattr(request.app.state, "gpu_docker_manager", None)
    if gpu_manager is None:
        gpu_manager = GPUDockerManager(
            default_image=settings.execution_default_docker_image,
        )

    info = await gpu_manager.get_gpu_info()
    info["gpu_enabled"] = settings.execution_gpu_enabled
    info["default_image"] = settings.execution_default_docker_image
    info["configured_runtime"] = settings.execution_gpu_runtime
    return info
