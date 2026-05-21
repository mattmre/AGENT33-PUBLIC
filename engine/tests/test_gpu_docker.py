"""Tests for GPU runtime detection, Docker image management, and execution route."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from agent33.execution.gpu import (
    CustomImageConfig,
    GPUConfig,
    GPUDockerManager,
    GPURuntime,
)
from agent33.execution.models import SandboxConfig

# ---------------------------------------------------------------------------
# GPUConfig model tests
# ---------------------------------------------------------------------------


class TestGPUConfig:
    """Validate GPUConfig defaults and field behaviour."""

    def test_defaults(self) -> None:
        cfg = GPUConfig()
        assert cfg.runtime == GPURuntime.NONE
        assert cfg.device_ids == []
        assert cfg.memory_limit == ""
        assert cfg.capabilities == ["compute", "utility"]

    def test_nvidia_runtime(self) -> None:
        cfg = GPUConfig(runtime=GPURuntime.NVIDIA, device_ids=["0", "1"])
        assert cfg.runtime == GPURuntime.NVIDIA
        assert cfg.device_ids == ["0", "1"]

    def test_amd_runtime(self) -> None:
        cfg = GPUConfig(runtime=GPURuntime.AMD, device_ids=["all"])
        assert cfg.runtime == GPURuntime.AMD
        assert cfg.device_ids == ["all"]

    def test_memory_limit_with_capabilities(self) -> None:
        cfg = GPUConfig(
            runtime=GPURuntime.NVIDIA,
            memory_limit="4g",
            capabilities=["compute", "utility", "graphics"],
        )
        assert cfg.memory_limit == "4g"
        assert "graphics" in cfg.capabilities

    def test_serialization_roundtrip(self) -> None:
        cfg = GPUConfig(
            runtime=GPURuntime.NVIDIA,
            device_ids=["0"],
            memory_limit="8g",
        )
        data = cfg.model_dump()
        restored = GPUConfig.model_validate(data)
        assert restored.runtime == GPURuntime.NVIDIA
        assert restored.device_ids == ["0"]
        assert restored.memory_limit == "8g"


# ---------------------------------------------------------------------------
# CustomImageConfig model tests
# ---------------------------------------------------------------------------


class TestCustomImageConfig:
    """Validate CustomImageConfig defaults and field behaviour."""

    def test_defaults(self) -> None:
        cfg = CustomImageConfig(image="pytorch/pytorch:latest")
        assert cfg.image == "pytorch/pytorch:latest"
        assert cfg.pull_policy == "if-not-present"
        assert cfg.registry_auth == {}
        assert cfg.build_context == ""

    def test_always_pull(self) -> None:
        cfg = CustomImageConfig(image="nvcr.io/nvidia/cuda:12.0-runtime", pull_policy="always")
        assert cfg.pull_policy == "always"

    def test_never_pull(self) -> None:
        cfg = CustomImageConfig(image="local-build:dev", pull_policy="never")
        assert cfg.pull_policy == "never"

    def test_with_registry_auth(self) -> None:
        cfg = CustomImageConfig(
            image="registry.example.com/myimage:1.0",
            registry_auth={"username": "user", "password": "pass"},
        )
        assert cfg.registry_auth["username"] == "user"

    def test_with_build_context(self) -> None:
        cfg = CustomImageConfig(
            image="local-gpu-image:latest",
            build_context="/path/to/Dockerfile",
        )
        assert cfg.build_context == "/path/to/Dockerfile"


# ---------------------------------------------------------------------------
# SandboxConfig GPU field tests
# ---------------------------------------------------------------------------


class TestSandboxConfigGPU:
    """Validate GPU-related fields on SandboxConfig."""

    def test_gpu_field_defaults_to_none(self) -> None:
        cfg = SandboxConfig()
        assert cfg.gpu is None
        assert cfg.custom_image is None
        assert cfg.image_pull_policy == "if-not-present"

    def test_gpu_field_accepts_dict(self) -> None:
        gpu_dict: dict[str, Any] = {
            "runtime": "nvidia",
            "device_ids": ["0"],
            "memory_limit": "4g",
            "capabilities": ["compute", "utility"],
        }
        cfg = SandboxConfig(gpu=gpu_dict)
        assert cfg.gpu is not None
        assert cfg.gpu["runtime"] == "nvidia"
        assert cfg.gpu["device_ids"] == ["0"]

    def test_custom_image_override(self) -> None:
        cfg = SandboxConfig(custom_image="pytorch/pytorch:2.0")
        assert cfg.custom_image == "pytorch/pytorch:2.0"

    def test_image_pull_policy_values(self) -> None:
        for policy in ("always", "if-not-present", "never"):
            cfg = SandboxConfig(image_pull_policy=policy)
            assert cfg.image_pull_policy == policy

    def test_gpu_config_roundtrip(self) -> None:
        """SandboxConfig with GPU dict survives serialization."""
        gpu_dict: dict[str, Any] = {"runtime": "amd", "device_ids": ["all"]}
        cfg = SandboxConfig(gpu=gpu_dict, custom_image="test:latest")
        data = cfg.model_dump()
        restored = SandboxConfig.model_validate(data)
        assert restored.gpu == gpu_dict
        assert restored.custom_image == "test:latest"


# ---------------------------------------------------------------------------
# GPUDockerManager: build_docker_args
# ---------------------------------------------------------------------------


class TestBuildDockerArgs:
    """Test GPUDockerManager.build_docker_args with various configurations."""

    def test_no_gpu_no_image(self) -> None:
        """With no GPU and no custom image, only sandbox limits + default image."""
        mgr = GPUDockerManager(default_image="python:3.11-slim")
        sandbox = SandboxConfig(memory_mb=256, cpu_cores=2)
        args = mgr.build_docker_args(sandbox=sandbox)

        assert "--memory" in args
        idx = args.index("--memory")
        assert args[idx + 1] == "256m"

        assert "--cpus" in args
        idx = args.index("--cpus")
        assert args[idx + 1] == "2"

        # Default image is last
        assert args[-1] == "python:3.11-slim"

        # No GPU flags
        assert "--gpus" not in args
        assert "--device" not in args

    def test_nvidia_gpu_all_devices(self) -> None:
        """NVIDIA GPU with all devices produces correct --gpus flag."""
        mgr = GPUDockerManager()
        gpu = GPUConfig(runtime=GPURuntime.NVIDIA, device_ids=["all"])
        args = mgr.build_docker_args(gpu=gpu)

        assert "--gpus" in args
        idx = args.index("--gpus")
        gpus_value = args[idx + 1]
        assert "device=all" in gpus_value
        assert "capabilities=compute,utility" in gpus_value

        # NVIDIA_VISIBLE_DEVICES env var
        assert "-e" in args
        env_idx = args.index("-e")
        assert "NVIDIA_VISIBLE_DEVICES=all" in args[env_idx + 1]

    def test_nvidia_gpu_specific_devices(self) -> None:
        """NVIDIA GPU with specific device IDs."""
        mgr = GPUDockerManager()
        gpu = GPUConfig(runtime=GPURuntime.NVIDIA, device_ids=["0", "2"])
        args = mgr.build_docker_args(gpu=gpu)

        assert "--gpus" in args
        idx = args.index("--gpus")
        gpus_value = args[idx + 1]
        assert "device=0,2" in gpus_value

    def test_nvidia_gpu_no_devices_defaults_to_all(self) -> None:
        """NVIDIA GPU with empty device list defaults to all."""
        mgr = GPUDockerManager()
        gpu = GPUConfig(runtime=GPURuntime.NVIDIA)
        args = mgr.build_docker_args(gpu=gpu)

        idx = args.index("--gpus")
        gpus_value = args[idx + 1]
        assert "device=all" in gpus_value

    def test_nvidia_gpu_with_memory_limit(self) -> None:
        """GPU memory limit adds --shm-size flag."""
        mgr = GPUDockerManager()
        gpu = GPUConfig(
            runtime=GPURuntime.NVIDIA,
            memory_limit="4g",
        )
        args = mgr.build_docker_args(gpu=gpu)

        assert "--shm-size" in args
        idx = args.index("--shm-size")
        assert args[idx + 1] == "4g"

    def test_nvidia_gpu_custom_capabilities(self) -> None:
        """Custom NVIDIA capabilities are reflected in --gpus value."""
        mgr = GPUDockerManager()
        gpu = GPUConfig(
            runtime=GPURuntime.NVIDIA,
            capabilities=["compute", "graphics", "video"],
        )
        args = mgr.build_docker_args(gpu=gpu)

        idx = args.index("--gpus")
        gpus_value = args[idx + 1]
        assert "capabilities=compute,graphics,video" in gpus_value

    def test_amd_gpu_all_devices(self) -> None:
        """AMD GPU with all devices passes /dev/kfd and /dev/dri."""
        mgr = GPUDockerManager()
        gpu = GPUConfig(runtime=GPURuntime.AMD, device_ids=["all"])
        args = mgr.build_docker_args(gpu=gpu)

        assert "--device" in args
        # Should have /dev/kfd and /dev/dri
        device_values = []
        for i, a in enumerate(args):
            if a == "--device" and i + 1 < len(args):
                device_values.append(args[i + 1])
        assert "/dev/kfd" in device_values
        assert "/dev/dri" in device_values

        assert "--group-add" in args
        gidx = args.index("--group-add")
        assert args[gidx + 1] == "video"

    def test_amd_gpu_specific_devices(self) -> None:
        """AMD GPU with specific device IDs maps to renderD nodes."""
        mgr = GPUDockerManager()
        gpu = GPUConfig(runtime=GPURuntime.AMD, device_ids=["0", "1"])
        args = mgr.build_docker_args(gpu=gpu)

        device_values = []
        for i, a in enumerate(args):
            if a == "--device" and i + 1 < len(args):
                device_values.append(args[i + 1])
        assert "/dev/dri/renderD128" in device_values  # device 0
        assert "/dev/dri/renderD129" in device_values  # device 1

    def test_custom_image_only(self) -> None:
        """Custom image without GPU replaces default image."""
        mgr = GPUDockerManager(default_image="python:3.11-slim")
        image_cfg = CustomImageConfig(image="pytorch/pytorch:2.0-cuda12")
        args = mgr.build_docker_args(image=image_cfg)

        assert args[-1] == "pytorch/pytorch:2.0-cuda12"

    def test_gpu_plus_custom_image(self) -> None:
        """GPU config combined with custom image produces both flags and image."""
        mgr = GPUDockerManager()
        gpu = GPUConfig(runtime=GPURuntime.NVIDIA, device_ids=["0"])
        image_cfg = CustomImageConfig(image="nvcr.io/nvidia/pytorch:23.10-py3")

        args = mgr.build_docker_args(gpu=gpu, image=image_cfg)

        # GPU flags present
        assert "--gpus" in args

        # Custom image is the last arg
        assert args[-1] == "nvcr.io/nvidia/pytorch:23.10-py3"

    def test_gpu_plus_sandbox_plus_image(self) -> None:
        """Full combination: sandbox limits + GPU + custom image."""
        mgr = GPUDockerManager()
        sandbox = SandboxConfig(memory_mb=1024, cpu_cores=4)
        gpu = GPUConfig(
            runtime=GPURuntime.NVIDIA,
            device_ids=["0", "1"],
            memory_limit="8g",
        )
        image_cfg = CustomImageConfig(image="ml-training:v3")

        args = mgr.build_docker_args(sandbox=sandbox, gpu=gpu, image=image_cfg)

        # Sandbox limits
        assert "--memory" in args
        mem_idx = args.index("--memory")
        assert args[mem_idx + 1] == "1024m"

        assert "--cpus" in args
        cpu_idx = args.index("--cpus")
        assert args[cpu_idx + 1] == "4"

        # GPU flags
        assert "--gpus" in args
        assert "--shm-size" in args

        # Custom image
        assert args[-1] == "ml-training:v3"

    def test_none_gpu_no_flags(self) -> None:
        """GPURuntime.NONE produces no GPU flags."""
        mgr = GPUDockerManager()
        gpu = GPUConfig(runtime=GPURuntime.NONE)
        args = mgr.build_docker_args(gpu=gpu)

        assert "--gpus" not in args
        assert "--device" not in args
        assert "--group-add" not in args

    def test_no_sandbox_no_resource_flags(self) -> None:
        """With sandbox=None, no --memory or --cpus flags."""
        mgr = GPUDockerManager()
        args = mgr.build_docker_args()

        assert "--memory" not in args
        assert "--cpus" not in args
        # Should only contain the default image
        assert len(args) == 1
        assert args[0] == "python:3.11-slim"


# ---------------------------------------------------------------------------
# GPUDockerManager: detect_gpu_runtime (mocked subprocess)
# ---------------------------------------------------------------------------


class TestDetectGPURuntime:
    """Test GPU runtime detection with mocked subprocess calls."""

    async def test_detect_nvidia(self) -> None:
        """Detects NVIDIA when nvidia-smi is available and succeeds."""
        mgr = GPUDockerManager()
        with patch.object(mgr, "_command_available", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.side_effect = lambda cmd: cmd == "nvidia-smi"
            result = await mgr.detect_gpu_runtime()
            assert result == GPURuntime.NVIDIA

    async def test_detect_amd(self) -> None:
        """Detects AMD when nvidia-smi fails but rocm-smi succeeds."""
        mgr = GPUDockerManager()
        with patch.object(mgr, "_command_available", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.side_effect = lambda cmd: cmd == "rocm-smi"
            result = await mgr.detect_gpu_runtime()
            assert result == GPURuntime.AMD

    async def test_detect_none(self) -> None:
        """Returns NONE when no GPU tools are available."""
        mgr = GPUDockerManager()
        with patch.object(mgr, "_command_available", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = False
            result = await mgr.detect_gpu_runtime()
            assert result == GPURuntime.NONE

    async def test_nvidia_preferred_over_amd(self) -> None:
        """When both runtimes are available, NVIDIA takes priority."""
        mgr = GPUDockerManager()
        with patch.object(mgr, "_command_available", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = True
            result = await mgr.detect_gpu_runtime()
            assert result == GPURuntime.NVIDIA


# ---------------------------------------------------------------------------
# GPUDockerManager: validate_image
# ---------------------------------------------------------------------------


class TestValidateImage:
    """Test Docker image validation/pull logic."""

    async def test_never_policy_image_exists(self) -> None:
        mgr = GPUDockerManager()
        with patch.object(mgr, "_image_exists", new_callable=AsyncMock, return_value=True):
            result = await mgr.validate_image("test:latest", pull_policy="never")
            assert result is True

    async def test_never_policy_image_missing(self) -> None:
        mgr = GPUDockerManager()
        with patch.object(mgr, "_image_exists", new_callable=AsyncMock, return_value=False):
            result = await mgr.validate_image("test:latest", pull_policy="never")
            assert result is False

    async def test_always_policy_pulls(self) -> None:
        mgr = GPUDockerManager()
        with patch.object(mgr, "_pull_image", new_callable=AsyncMock, return_value=True):
            result = await mgr.validate_image("test:latest", pull_policy="always")
            assert result is True

    async def test_always_policy_pull_fails(self) -> None:
        mgr = GPUDockerManager()
        with patch.object(mgr, "_pull_image", new_callable=AsyncMock, return_value=False):
            result = await mgr.validate_image("test:latest", pull_policy="always")
            assert result is False

    async def test_if_not_present_exists(self) -> None:
        """If image exists locally, do not pull."""
        mgr = GPUDockerManager()
        with (
            patch.object(mgr, "_image_exists", new_callable=AsyncMock, return_value=True),
            patch.object(mgr, "_pull_image", new_callable=AsyncMock) as mock_pull,
        ):
            result = await mgr.validate_image("test:latest", pull_policy="if-not-present")
            assert result is True
            mock_pull.assert_not_called()

    async def test_if_not_present_pulls_when_missing(self) -> None:
        """If image is missing, pull it."""
        mgr = GPUDockerManager()
        with (
            patch.object(mgr, "_image_exists", new_callable=AsyncMock, return_value=False),
            patch.object(mgr, "_pull_image", new_callable=AsyncMock, return_value=True),
        ):
            result = await mgr.validate_image("test:latest", pull_policy="if-not-present")
            assert result is True


# ---------------------------------------------------------------------------
# GPUDockerManager: get_gpu_info
# ---------------------------------------------------------------------------


class TestGetGPUInfo:
    """Test GPU info retrieval."""

    async def test_no_gpu(self) -> None:
        mgr = GPUDockerManager()
        with patch.object(
            mgr, "detect_gpu_runtime", new_callable=AsyncMock, return_value=GPURuntime.NONE
        ):
            info = await mgr.get_gpu_info()
            assert info["runtime"] == "none"
            assert info["available"] is False
            assert info["devices"] == []

    async def test_nvidia_gpu_info(self) -> None:
        mgr = GPUDockerManager()
        mock_nvidia_data = {
            "devices": [
                {"index": "0", "name": "RTX 3090", "memory_mb": "24576", "driver_version": "535"},
            ],
            "driver_version": "535",
            "device_count": 1,
        }
        with (
            patch.object(
                mgr,
                "detect_gpu_runtime",
                new_callable=AsyncMock,
                return_value=GPURuntime.NVIDIA,
            ),
            patch.object(
                mgr, "_nvidia_info", new_callable=AsyncMock, return_value=mock_nvidia_data
            ),
        ):
            info = await mgr.get_gpu_info()
            assert info["runtime"] == "nvidia"
            assert info["available"] is True
            assert info["device_count"] == 1
            assert info["devices"][0]["name"] == "RTX 3090"
            assert info["driver_version"] == "535"

    async def test_amd_gpu_info(self) -> None:
        mgr = GPUDockerManager()
        mock_amd_data = {
            "devices": [{"index": "0", "raw": "GPU[0]"}],
            "driver_version": "",
            "device_count": 1,
        }
        with (
            patch.object(
                mgr, "detect_gpu_runtime", new_callable=AsyncMock, return_value=GPURuntime.AMD
            ),
            patch.object(mgr, "_amd_info", new_callable=AsyncMock, return_value=mock_amd_data),
        ):
            info = await mgr.get_gpu_info()
            assert info["runtime"] == "amd"
            assert info["available"] is True
            assert info["device_count"] == 1


# ---------------------------------------------------------------------------
# GPURuntime enum tests
# ---------------------------------------------------------------------------


class TestGPURuntime:
    """Verify GPURuntime StrEnum values."""

    def test_values(self) -> None:
        assert GPURuntime.NVIDIA == "nvidia"
        assert GPURuntime.AMD == "amd"
        assert GPURuntime.NONE == "none"

    def test_from_string(self) -> None:
        assert GPURuntime("nvidia") == GPURuntime.NVIDIA
        assert GPURuntime("amd") == GPURuntime.AMD
        assert GPURuntime("none") == GPURuntime.NONE


# ---------------------------------------------------------------------------
# API route test
# ---------------------------------------------------------------------------


class TestGPUInfoRoute:
    """Test the GET /v1/execution/gpu-info endpoint."""

    def test_gpu_info_endpoint(self) -> None:
        """Endpoint returns GPU info with feature-flag status."""
        from fastapi.testclient import TestClient

        from agent33.main import app
        from agent33.security.auth import create_access_token

        # Install a mock GPUDockerManager on app.state
        mock_manager = MagicMock(spec=GPUDockerManager)
        mock_manager.get_gpu_info = AsyncMock(
            return_value={
                "runtime": "none",
                "available": False,
                "devices": [],
                "driver_version": "",
            }
        )
        app.state.gpu_docker_manager = mock_manager

        token = create_access_token("test-user", scopes=["admin"])
        client = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        try:
            response = client.get("/v1/execution/gpu-info")

            assert response.status_code == 200
            data = response.json()
            assert "runtime" in data
            assert "available" in data
            assert "gpu_enabled" in data
            assert "default_image" in data
            assert "configured_runtime" in data
            assert data["runtime"] == "none"
            assert data["available"] is False
            assert data["gpu_enabled"] is False
            assert data["configured_runtime"] == "nvidia"
        finally:
            # Clean up mock state
            if hasattr(app.state, "gpu_docker_manager"):
                del app.state.gpu_docker_manager

    def test_gpu_info_endpoint_no_auth_returns_401(self) -> None:
        """Endpoint returns 401 without authentication."""
        from fastapi.testclient import TestClient

        from agent33.main import app

        client = TestClient(app)
        response = client.get("/v1/execution/gpu-info")
        assert response.status_code == 401
