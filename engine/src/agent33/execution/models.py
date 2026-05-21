"""Pydantic models for the code execution contract and adapter definitions."""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Sandbox configuration
# ---------------------------------------------------------------------------


class FilesystemPolicy(BaseModel):
    """Filesystem access rules for sandboxed execution."""

    read: list[str] = Field(default_factory=list)
    write: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class NetworkPolicy(BaseModel):
    """Network access rules for sandboxed execution."""

    enabled: bool = False
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class ProcessPolicy(BaseModel):
    """Process limits for sandboxed execution."""

    max_children: int = Field(default=10, ge=0, le=100)
    allow_fork: bool = True


class SandboxConfig(BaseModel):
    """Resource and access limits applied during code execution."""

    timeout_ms: int = Field(default=30_000, ge=1_000, le=600_000)
    memory_mb: int = Field(default=512, ge=64, le=4096)
    cpu_cores: int = Field(default=1, ge=1, le=4)
    filesystem: FilesystemPolicy = Field(default_factory=FilesystemPolicy)
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)
    processes: ProcessPolicy = Field(default_factory=ProcessPolicy)

    # GPU passthrough (serializable dict to avoid circular imports)
    gpu: dict[str, Any] | None = None
    # Docker image override
    custom_image: str | None = None
    image_pull_policy: str = "if-not-present"


# ---------------------------------------------------------------------------
# Execution inputs / outputs
# ---------------------------------------------------------------------------


class ExecutionInputs(BaseModel):
    """Inputs supplied to an execution contract."""

    command: str
    arguments: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    working_directory: str | None = None
    input_files: list[str] = Field(default_factory=list)
    stdin: str | None = None


class OutputSpec(BaseModel):
    """Expected output description (informational)."""

    stdout: str = "captured"
    stderr: str = "captured"
    exit_code: int | None = None
    output_files: list[str] = Field(default_factory=list)


class OutputArtifact(BaseModel):
    """Structured artifact captured during execution."""

    mime_type: str
    data: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionContract(BaseModel):
    """Full contract that governs a single code execution."""

    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_id: str
    adapter_id: str | None = None
    inputs: ExecutionInputs
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    outputs: OutputSpec = Field(default_factory=OutputSpec)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """Result returned after executing a contract."""

    execution_id: str
    success: bool
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    output_files: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    error: str | None = None
    truncated: bool = False
    artifacts: list[OutputArtifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adapter definitions
# ---------------------------------------------------------------------------


class AdapterType(StrEnum):
    """Supported adapter transport types."""

    CLI = "cli"
    API = "api"
    SDK = "sdk"
    MCP = "mcp"
    KERNEL = "kernel"


class AdapterStatus(StrEnum):
    """Lifecycle status of an adapter definition."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"


class CLIInterface(BaseModel):
    """Interface spec for CLI-based adapters."""

    executable: str
    base_args: list[str] = Field(default_factory=list)
    arg_mapping: dict[str, str] = Field(default_factory=dict)
    env_mapping: dict[str, str] = Field(default_factory=dict)


class APIInterface(BaseModel):
    """Interface spec for REST API adapters."""

    base_url: str
    auth_method: str = "none"
    headers: dict[str, str] = Field(default_factory=dict)
    endpoint_mapping: dict[str, str] = Field(default_factory=dict)


class KernelContainerPolicy(BaseModel):
    """Container runtime controls for kernel-backed execution."""

    enabled: bool = False
    image: str = "quay.io/jupyter/minimal-notebook:python-3.11"
    allowed_images: list[str] = Field(default_factory=list)
    network_enabled: bool = False
    mount_working_directory: bool = True
    container_workdir: str = "/workspace"
    extra_run_args: list[str] = Field(default_factory=list)


class KernelInterface(BaseModel):
    """Interface spec for Jupyter kernel adapters."""

    kernel_name: str = "python3"
    max_sessions: int = Field(default=10, ge=1, le=100)
    idle_timeout_seconds: float = Field(default=300.0, ge=1.0, le=86_400.0)
    startup_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    execution_timeout_seconds: float = Field(default=60.0, ge=1.0, le=3_600.0)
    container: KernelContainerPolicy = Field(default_factory=KernelContainerPolicy)


class RetryConfig(BaseModel):
    """Retry behaviour for adapter error handling."""

    max_attempts: int = Field(default=1, ge=1, le=10)
    backoff_ms: int = Field(default=0, ge=0)
    retryable_codes: list[int] = Field(default_factory=list)


class FallbackConfig(BaseModel):
    """Fallback adapter for error handling."""

    adapter_id: str
    condition: str = ""


class ErrorHandling(BaseModel):
    """Error handling configuration for an adapter."""

    retry: RetryConfig = Field(default_factory=RetryConfig)
    fallback: FallbackConfig | None = None


class AdapterDefinition(BaseModel):
    """Complete definition of an execution adapter."""

    adapter_id: str
    name: str
    version: str = "1.0.0"
    tool_id: str
    type: AdapterType
    cli: CLIInterface | None = None
    api: APIInterface | None = None
    kernel: KernelInterface | None = None
    error_handling: ErrorHandling = Field(default_factory=ErrorHandling)
    sandbox_override: dict[str, Any] = Field(default_factory=dict)
    status: AdapterStatus = AdapterStatus.ACTIVE
    metadata: dict[str, Any] = Field(default_factory=dict)
