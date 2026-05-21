"""GPU runtime detection and Docker image management for execution adapters."""

from __future__ import annotations

import asyncio
import shutil
import sys
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Enums & config models
# ---------------------------------------------------------------------------


class GPURuntime(StrEnum):
    """Supported GPU runtime backends."""

    NVIDIA = "nvidia"
    AMD = "amd"
    NONE = "none"


class GPUConfig(BaseModel):
    """GPU passthrough configuration for Docker-based execution."""

    runtime: GPURuntime = GPURuntime.NONE
    device_ids: list[str] = Field(default_factory=list)
    memory_limit: str = ""
    capabilities: list[str] = Field(default_factory=lambda: ["compute", "utility"])


class CustomImageConfig(BaseModel):
    """Custom Docker image configuration for execution adapters."""

    image: str
    pull_policy: str = "if-not-present"
    registry_auth: dict[str, str] = Field(default_factory=dict)
    build_context: str = ""


# ---------------------------------------------------------------------------
# GPUDockerManager
# ---------------------------------------------------------------------------


class GPUDockerManager:
    """Manage GPU passthrough flags and custom image handling for Docker execution.

    This class produces the ``docker run`` argument fragments needed to enable
    GPU hardware acceleration (NVIDIA or AMD) and to resolve custom container
    images with configurable pull policies.
    """

    def __init__(self, default_image: str = "python:3.11-slim") -> None:
        self._default_image = default_image

    # -- GPU runtime detection ------------------------------------------------

    async def detect_gpu_runtime(self) -> GPURuntime:
        """Probe the host for an available GPU runtime.

        Detection order:
        1. ``nvidia-smi`` on PATH  -> :pyattr:`GPURuntime.NVIDIA`
        2. ``rocm-smi`` on PATH    -> :pyattr:`GPURuntime.AMD`
        3. Otherwise               -> :pyattr:`GPURuntime.NONE`

        The check never raises; missing tools are treated as "no GPU".
        """
        if await self._command_available("nvidia-smi"):
            return GPURuntime.NVIDIA
        if await self._command_available("rocm-smi"):
            return GPURuntime.AMD
        return GPURuntime.NONE

    # -- Docker argument builder ----------------------------------------------

    def build_docker_args(
        self,
        sandbox: Any | None = None,
        gpu: GPUConfig | None = None,
        image: CustomImageConfig | None = None,
    ) -> list[str]:
        """Build the ``docker run`` argument list.

        The returned list does **not** include the ``docker run`` prefix itself,
        only the flags/arguments that follow it.

        Args:
            sandbox: Optional :class:`SandboxConfig` for resource limits
                     (memory, cpu).
            gpu: Optional GPU passthrough configuration.
            image: Optional custom image override.

        Returns:
            A list of string arguments suitable for ``docker run``.
        """
        args: list[str] = []

        # -- Sandbox resource limits ------------------------------------------
        if sandbox is not None:
            memory_mb: int = getattr(sandbox, "memory_mb", 512)
            cpu_cores: int = getattr(sandbox, "cpu_cores", 1)
            args.extend(["--memory", f"{memory_mb}m"])
            args.extend(["--cpus", str(cpu_cores)])

        # -- GPU flags --------------------------------------------------------
        if gpu is not None and gpu.runtime != GPURuntime.NONE:
            args.extend(self._build_gpu_flags(gpu))

        # -- Image selection --------------------------------------------------
        resolved_image = self._resolve_image(image)
        args.append(resolved_image)

        return args

    # -- Image validation / pull ---------------------------------------------

    async def validate_image(self, image: str, pull_policy: str = "if-not-present") -> bool:
        """Ensure the requested Docker image is available locally.

        Args:
            image: Docker image name (with optional tag).
            pull_policy: One of ``always``, ``if-not-present``, ``never``.

        Returns:
            ``True`` if the image is available after the operation,
            ``False`` otherwise.
        """
        if pull_policy == "never":
            return await self._image_exists(image)

        if pull_policy == "always":
            return await self._pull_image(image)

        # "if-not-present" (default)
        if await self._image_exists(image):
            return True
        return await self._pull_image(image)

    # -- GPU info -------------------------------------------------------------

    async def get_gpu_info(self) -> dict[str, Any]:
        """Return information about the available GPU hardware.

        Returns a dict with keys ``runtime``, ``available``, and
        runtime-specific details (device count, driver version, etc.).
        Falls back gracefully when no GPU tooling is present.
        """
        runtime = await self.detect_gpu_runtime()
        info: dict[str, Any] = {
            "runtime": runtime.value,
            "available": runtime != GPURuntime.NONE,
            "devices": [],
            "driver_version": "",
        }

        if runtime == GPURuntime.NVIDIA:
            info.update(await self._nvidia_info())
        elif runtime == GPURuntime.AMD:
            info.update(await self._amd_info())

        return info

    # -- Private helpers ------------------------------------------------------

    def _build_gpu_flags(self, gpu: GPUConfig) -> list[str]:
        """Translate a :class:`GPUConfig` into Docker CLI flags."""
        flags: list[str] = []

        if gpu.runtime == GPURuntime.NVIDIA:
            # Determine device spec
            if gpu.device_ids:
                device_spec = "all" if gpu.device_ids == ["all"] else ",".join(gpu.device_ids)
            else:
                device_spec = "all"

            # Build --gpus flag with capabilities
            caps = ",".join(gpu.capabilities) if gpu.capabilities else "compute,utility"
            # No shell quoting needed: subprocess passes args directly to docker.
            gpus_value = f"device={device_spec},capabilities={caps}"
            flags.extend(["--gpus", gpus_value])

            # NVIDIA_VISIBLE_DEVICES env var for compatibility
            flags.extend(["-e", f"NVIDIA_VISIBLE_DEVICES={device_spec}"])

            # GPU memory limit (NVIDIA-specific env var)
            if gpu.memory_limit:
                flags.extend(["-e", f"NVIDIA_DRIVER_CAPABILITIES={caps}"])

        elif gpu.runtime == GPURuntime.AMD:
            # AMD ROCm passthrough uses --device for GPU nodes
            if gpu.device_ids and gpu.device_ids != ["all"]:
                for dev_id in gpu.device_ids:
                    flags.extend(["--device", f"/dev/dri/renderD{128 + int(dev_id)}"])
            else:
                # Pass all render nodes
                flags.extend(["--device", "/dev/kfd"])
                flags.extend(["--device", "/dev/dri"])

            flags.extend(["--group-add", "video"])
            flags.extend(["-e", "ROC_ENABLE_PRE_VEGA=1"])

        # GPU memory limit expressed as a container-level constraint
        if gpu.memory_limit:
            flags.extend(["--shm-size", gpu.memory_limit])

        return flags

    def _resolve_image(self, image_config: CustomImageConfig | None) -> str:
        """Return the Docker image name to use."""
        if image_config is not None and image_config.image:
            return image_config.image
        return self._default_image

    async def _command_available(self, cmd: str) -> bool:
        """Check whether *cmd* is on PATH and can be executed."""
        if shutil.which(cmd) is None:
            return False

        try:
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return proc.returncode == 0
        except (TimeoutError, OSError):
            return False

    async def _image_exists(self, image: str) -> bool:
        """Check whether a Docker image exists locally."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "image",
                "inspect",
                image,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.communicate()
            return proc.returncode == 0
        except (OSError, FileNotFoundError):
            return False

    async def _pull_image(self, image: str) -> bool:
        """Pull a Docker image. Returns True on success."""
        try:
            logger.info("docker_image_pull_start", image=image)
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "pull",
                image,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr_bytes = await proc.communicate()
            if proc.returncode != 0:
                stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
                logger.warning("docker_image_pull_failed", image=image, error=stderr)
                return False
            logger.info("docker_image_pull_complete", image=image)
            return True
        except (OSError, FileNotFoundError):
            logger.warning("docker_not_available_for_pull", image=image)
            return False

    async def _nvidia_info(self) -> dict[str, Any]:
        """Query nvidia-smi for GPU details."""
        result: dict[str, Any] = {"devices": [], "driver_version": ""}
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode == 0:
                lines = stdout_bytes.decode("utf-8", errors="replace").strip().splitlines()
                devices: list[dict[str, str]] = []
                for line in lines:
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 4:
                        devices.append(
                            {
                                "index": parts[0],
                                "name": parts[1],
                                "memory_mb": parts[2],
                                "driver_version": parts[3],
                            }
                        )
                        if not result["driver_version"]:
                            result["driver_version"] = parts[3]
                result["devices"] = devices
                result["device_count"] = len(devices)
        except (TimeoutError, OSError):
            logger.debug("nvidia_smi_query_failed")
        return result

    async def _amd_info(self) -> dict[str, Any]:
        """Query rocm-smi for GPU details."""
        result: dict[str, Any] = {"devices": [], "driver_version": ""}
        try:
            proc = await asyncio.create_subprocess_exec(
                "rocm-smi",
                "--showid",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            if proc.returncode == 0:
                output = stdout_bytes.decode("utf-8", errors="replace").strip()
                # Parse line count as rough device count indicator
                lines = [ln for ln in output.splitlines() if ln.strip() and "GPU" in ln]
                result["devices"] = [{"index": str(i), "raw": ln} for i, ln in enumerate(lines)]
                result["device_count"] = len(lines)
        except (TimeoutError, OSError):
            logger.debug("rocm_smi_query_failed")
        return result
