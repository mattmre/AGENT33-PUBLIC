"""Jupyter kernel adapter for stateful code execution."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import socket
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

from agent33.execution.adapters.base import BaseAdapter
from agent33.execution.models import (
    AdapterDefinition,
    AdapterType,
    ExecutionContract,
    ExecutionResult,
    KernelContainerPolicy,
    KernelInterface,
    OutputArtifact,
    SandboxConfig,
)

logger = logging.getLogger(__name__)

_HAS_JUPYTER = False
try:
    import jupyter_client  # type: ignore[import-not-found]  # noqa: F401

    _HAS_JUPYTER = True
except ImportError:
    pass


class _KernelSessionProtocol(Protocol):
    session_id: str
    kernel_name: str
    last_used: float

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def execute(
        self,
        code: str,
        timeout: float = 60.0,
    ) -> tuple[bool, str, str, list[OutputArtifact]]: ...

    def matches_sandbox(self, sandbox: SandboxConfig | None) -> bool: ...

    @property
    def is_alive(self) -> bool: ...


def _language_to_kernel(language: str) -> str:
    """Map a language hint to a kernel name."""
    mapping = {
        "python": "python3",
        "python3": "python3",
        "r": "ir",
        "julia": "julia-1.9",
        "javascript": "javascript",
        "typescript": "tslab",
    }
    return mapping.get(language.lower(), "python3")


def _serialize_artifact_value(value: Any) -> str:
    """Normalize Jupyter output payloads into strings."""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value)
    except TypeError:
        return str(value)


def _allocate_port() -> int:
    """Reserve an available localhost port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _build_connection_info(*, ip: str, key: str) -> dict[str, Any]:
    """Build connection info compatible with ipykernel."""
    return {
        "shell_port": _allocate_port(),
        "iopub_port": _allocate_port(),
        "stdin_port": _allocate_port(),
        "control_port": _allocate_port(),
        "hb_port": _allocate_port(),
        "ip": ip,
        "key": key,
        "transport": "tcp",
        "signature_scheme": "hmac-sha256",
    }


def _sanitize_container_name(session_id: str) -> str:
    """Generate a Docker-safe container name."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in session_id.lower())
    return f"agent33-kernel-{safe[:40]}"


def _filter_conflicting_run_args(extra_run_args: list[str]) -> list[str]:
    """Drop resource flags that are now governed by SandboxConfig."""
    filtered: list[str] = []
    skip_next = False

    for arg in extra_run_args:
        if skip_next:
            skip_next = False
            continue
        if arg in {"--memory", "--cpus"}:
            skip_next = True
            continue
        if arg.startswith("--memory=") or arg.startswith("--cpus="):
            continue
        filtered.append(arg)

    return filtered


def _build_directory_preamble(code: str, target_directory: str | None) -> str:
    """Prepend a Python chdir snippet when a working directory is requested."""
    if not target_directory:
        return code
    escaped = json.dumps(target_directory)
    return f"import os\nos.chdir({escaped})\n{code}"


async def _build_async_kernel_client(connection_file: Path) -> Any:
    """Create a Jupyter async kernel client from a connection file."""
    import jupyter_client

    with connection_file.open("r", encoding="utf-8") as handle:
        info = json.load(handle)

    client = jupyter_client.AsyncKernelClient()
    if hasattr(client, "load_connection_info"):
        client.load_connection_info(info)
    else:
        for key, value in info.items():
            setattr(client, key, value)
    return client


async def _collect_kernel_output(
    client: Any,
    msg_id: str,
    timeout: float,
) -> tuple[bool, str, str, list[OutputArtifact]]:
    """Collect stream, rich output, and errors from IOPub."""
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    artifacts: list[OutputArtifact] = []
    success = True
    deadline = time.monotonic() + timeout

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Kernel execution timed out after {timeout}s")

        try:
            message = await asyncio.wait_for(
                client.get_iopub_msg(),
                timeout=min(remaining, 5.0),
            )
        except TimeoutError:
            continue

        if message.get("parent_header", {}).get("msg_id") != msg_id:
            continue

        msg_type = message.get("msg_type")
        content = message.get("content", {})

        if msg_type == "stream":
            text = str(content.get("text", ""))
            if content.get("name") == "stderr":
                stderr_parts.append(text)
            else:
                stdout_parts.append(text)
        elif msg_type in {"display_data", "execute_result"}:
            metadata = content.get("metadata", {})
            for mime_type, value in content.get("data", {}).items():
                artifact_metadata = (
                    metadata.get(mime_type, {}) if isinstance(metadata, dict) else {}
                )
                artifacts.append(
                    OutputArtifact(
                        mime_type=mime_type,
                        data=_serialize_artifact_value(value),
                        metadata=artifact_metadata if isinstance(artifact_metadata, dict) else {},
                    )
                )
        elif msg_type == "error":
            success = False
            traceback_lines = content.get("traceback", [])
            if traceback_lines:
                stderr_parts.append("\n".join(str(line) for line in traceback_lines))
            else:
                ename = content.get("ename", "ExecutionError")
                evalue = content.get("evalue", "")
                stderr_parts.append(f"{ename}: {evalue}".strip(": "))
        elif msg_type == "status" and content.get("execution_state") == "idle":
            break

    return success, "".join(stdout_parts), "".join(stderr_parts), artifacts


class KernelSession:
    """Manage a local Jupyter kernel session."""

    def __init__(
        self,
        session_id: str,
        kernel_name: str = "python3",
        *,
        startup_timeout: float = 30.0,
        manager_factory: Any | None = None,
    ) -> None:
        self.session_id = session_id
        self.kernel_name = kernel_name
        self.created_at = time.time()
        self.last_used = time.time()
        self._startup_timeout = startup_timeout
        self._manager_factory = manager_factory
        self._manager: Any = None
        self._client: Any = None
        self._started = False

    async def start(self) -> None:
        """Start the kernel and wait until it is ready."""
        if not _HAS_JUPYTER:
            msg = "jupyter_client is not installed. Install with: pip install agent33[jupyter]"
            raise RuntimeError(msg)

        import jupyter_client

        manager_factory = self._manager_factory or jupyter_client.AsyncKernelManager
        self._manager = manager_factory(kernel_name=self.kernel_name)
        await self._manager.start_kernel()
        self._client = self._manager.client()
        self._client.start_channels()
        try:
            await asyncio.wait_for(self._client.wait_for_ready(), timeout=self._startup_timeout)
        except TimeoutError as exc:
            await self.stop()
            msg = f"Kernel failed to start within {self._startup_timeout} seconds"
            raise RuntimeError(msg) from exc
        self._started = True

    async def stop(self) -> None:
        """Shutdown the kernel."""
        if self._client:
            with suppress(Exception):
                self._client.stop_channels()
        if self._manager and self._manager.is_alive():
            with suppress(Exception):
                await self._manager.shutdown_kernel(now=True)
        self._started = False

    async def execute(
        self,
        code: str,
        timeout: float = 60.0,
    ) -> tuple[bool, str, str, list[OutputArtifact]]:
        """Execute code and capture stream + rich outputs."""
        if not self._started or not self._client:
            raise RuntimeError("Kernel not started")
        self.last_used = time.time()
        msg_id = self._client.execute(code)
        return await _collect_kernel_output(self._client, msg_id, timeout)

    def matches_sandbox(self, sandbox: SandboxConfig | None) -> bool:
        """Local kernels do not persist container resource limits between calls."""
        del sandbox
        return True

    @property
    def is_alive(self) -> bool:
        if self._manager is None:
            return False
        return bool(self._manager.is_alive())


class DockerKernelSession:
    """Manage a Docker-backed Jupyter kernel session."""

    def __init__(
        self,
        session_id: str,
        kernel_name: str,
        *,
        policy: KernelContainerPolicy,
        startup_timeout: float = 30.0,
        working_directory: str | None = None,
        sandbox: SandboxConfig | None = None,
    ) -> None:
        self.session_id = session_id
        self.kernel_name = kernel_name
        self.created_at = time.time()
        self.last_used = time.time()
        self._policy = policy
        self._sandbox = sandbox or SandboxConfig()
        self._startup_timeout = startup_timeout
        self._working_directory = working_directory
        self._runtime_dir: Path | None = None
        self._host_connection_file: Path | None = None
        self._container_name = _sanitize_container_name(session_id)
        self._container_id: str | None = None
        self._client: Any = None
        self._started = False

    async def start(self) -> None:
        """Start an ipykernel inside a Docker container."""
        if not _HAS_JUPYTER:
            msg = "jupyter_client is not installed. Install with: pip install agent33[jupyter]"
            raise RuntimeError(msg)
        if shutil.which("docker") is None:
            raise RuntimeError("docker executable not found on PATH")
        if self._policy.allowed_images and self._policy.image not in self._policy.allowed_images:
            raise RuntimeError(f"Docker image '{self._policy.image}' is not permitted")

        runtime_dir = Path(tempfile.mkdtemp(prefix=f"agent33-kernel-{self.session_id}-"))
        host_connection_file = runtime_dir / "kernel-host.json"
        container_connection_file = runtime_dir / "kernel-container.json"
        connection_key = uuid.uuid4().hex
        host_info = _build_connection_info(ip="127.0.0.1", key=connection_key)
        container_info = {**host_info, "ip": "0.0.0.0"}

        host_connection_file.write_text(json.dumps(host_info), encoding="utf-8")
        container_connection_file.write_text(json.dumps(container_info), encoding="utf-8")

        command = self._build_docker_command(runtime_dir, host_info)
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
            shutil.rmtree(runtime_dir, ignore_errors=True)
            raise RuntimeError(f"docker run failed: {stderr or 'unknown error'}")

        self._runtime_dir = runtime_dir
        self._host_connection_file = host_connection_file
        self._container_id = stdout_bytes.decode("utf-8", errors="replace").strip() or None
        try:
            await self._assert_container_running(stage="startup")
            self._client = await _build_async_kernel_client(host_connection_file)
            self._client.start_channels()
            await asyncio.wait_for(self._client.wait_for_ready(), timeout=self._startup_timeout)
            await self._assert_container_running(stage="readiness")
        except TimeoutError as exc:
            await self.stop()
            raise RuntimeError(
                f"Docker kernel failed to start within {self._startup_timeout} seconds"
            ) from exc
        except Exception:
            await self.stop()
            raise
        self._started = True

    async def _inspect_container_state(self) -> tuple[bool, str]:
        """Return whether the managed container is still running."""
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            "--format",
            "{{.State.Status}}",
            self._container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        if proc.returncode != 0:
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
            return False, stderr or "inspect_failed"
        status = stdout_bytes.decode("utf-8", errors="replace").strip() or "unknown"
        return status == "running", status

    async def _assert_container_running(self, *, stage: str) -> None:
        """Fail early when the container exits before the kernel is ready."""
        running, status = await self._inspect_container_state()
        if not running:
            raise RuntimeError(f"Docker kernel container is not running during {stage}: {status}")

    def _build_docker_command(
        self,
        runtime_dir: Path,
        connection_info: dict[str, Any],
    ) -> list[str]:
        """Build the `docker run` command for the kernel container."""
        command = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            self._container_name,
            "--label",
            "agent33.managed=true",
            "--label",
            f"agent33.session_id={self.session_id}",
            "--label",
            f"agent33.kernel_name={self.kernel_name}",
        ]

        if self._policy.network_enabled:
            command.extend(["--network", "bridge"])
        else:
            command.extend(["--network", "none"])

        for port_key in ("shell_port", "iopub_port", "stdin_port", "control_port", "hb_port"):
            port = int(connection_info[port_key])
            command.extend(["-p", f"{port}:{port}"])

        command.extend(["-v", f"{runtime_dir}:/agent33-runtime"])

        if self._policy.mount_working_directory and self._working_directory:
            command.extend(
                [
                    "-v",
                    f"{self._working_directory}:{self._policy.container_workdir}",
                    "-w",
                    self._policy.container_workdir,
                ]
            )

        command.extend(_filter_conflicting_run_args(self._policy.extra_run_args))
        command.extend(
            [
                "--memory",
                f"{self._sandbox.memory_mb}m",
                "--cpus",
                str(self._sandbox.cpu_cores),
            ]
        )
        command.append(self._policy.image)
        command.extend(
            [
                "python",
                "-m",
                "ipykernel_launcher",
                "-f",
                "/agent33-runtime/kernel-container.json",
            ]
        )
        return command

    async def stop(self) -> None:
        """Force-remove the running container and clean temp files."""
        if self._client:
            with suppress(Exception):
                self._client.stop_channels()
        if self._container_name:
            with suppress(Exception):
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "rm",
                    "-f",
                    self._container_name,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate()
        if self._runtime_dir is not None:
            shutil.rmtree(self._runtime_dir, ignore_errors=True)
        self._started = False

    async def execute(
        self,
        code: str,
        timeout: float = 60.0,
    ) -> tuple[bool, str, str, list[OutputArtifact]]:
        """Execute code within the container-backed kernel."""
        if not self._started or not self._client:
            raise RuntimeError("Kernel not started")
        self.last_used = time.time()
        msg_id = self._client.execute(code)
        return await _collect_kernel_output(self._client, msg_id, timeout)

    def matches_sandbox(self, sandbox: SandboxConfig | None) -> bool:
        """Reject silent resource-limit changes on reused stateful sessions."""
        if sandbox is None:
            return True
        return self._sandbox == sandbox

    @property
    def is_alive(self) -> bool:
        return self._started


class KernelSessionManager:
    """Manage local or Docker-backed kernel sessions."""

    def __init__(
        self,
        *,
        max_sessions: int = 10,
        idle_timeout: float = 300.0,
        session_factory: Any | None = None,
    ) -> None:
        self._sessions: dict[str, _KernelSessionProtocol] = {}
        self._max_sessions = max_sessions
        self._idle_timeout = idle_timeout
        self._session_factory = session_factory or (
            lambda session_id, kernel_name, working_directory=None, sandbox=None: KernelSession(
                session_id,
                kernel_name,
            )
        )
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        session_id: str,
        kernel_name: str = "python3",
        working_directory: str | None = None,
        sandbox: SandboxConfig | None = None,
    ) -> _KernelSessionProtocol:
        """Get an existing session or create a new one."""
        async with self._lock:
            if session_id in self._sessions:
                session = self._sessions[session_id]
                if session.is_alive:
                    if not session.matches_sandbox(sandbox):
                        raise RuntimeError(
                            f"Sandbox configuration for session '{session_id}' does not match "
                            "the running kernel session"
                        )
                    return session
                del self._sessions[session_id]

            if len(self._sessions) >= self._max_sessions:
                await self._reap_idle()
            if len(self._sessions) >= self._max_sessions:
                raise RuntimeError(f"Maximum kernel sessions ({self._max_sessions}) reached")

            session = self._session_factory(
                session_id,
                kernel_name,
                working_directory,
                sandbox,
            )
            await session.start()
            self._sessions[session_id] = session
            return session

    async def remove(self, session_id: str) -> None:
        """Stop and remove a session."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is not None:
                await session.stop()

    async def _reap_idle(self) -> None:
        now = time.time()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session.last_used > self._idle_timeout
        ]
        for session_id in expired:
            session = self._sessions.pop(session_id)
            await session.stop()
            logger.info("reaped_idle_kernel_session %s", session_id)

    async def shutdown_all(self) -> None:
        """Shutdown all sessions."""
        for session in self._sessions.values():
            await session.stop()
        self._sessions.clear()

    @property
    def active_count(self) -> int:
        return len(self._sessions)


class JupyterAdapter(BaseAdapter):
    """Execute Python or notebook-style code through Jupyter kernels."""

    def __init__(
        self,
        definition: AdapterDefinition,
        *,
        session_manager: KernelSessionManager | None = None,
    ) -> None:
        if definition.type != AdapterType.KERNEL:
            raise ValueError("JupyterAdapter requires a kernel adapter definition")
        if definition.kernel is None:
            raise ValueError("JupyterAdapter requires a 'kernel' interface on the adapter")

        super().__init__(definition)
        self._kernel = definition.kernel
        self._session_manager = session_manager or KernelSessionManager(
            max_sessions=self._kernel.max_sessions,
            idle_timeout=self._kernel.idle_timeout_seconds,
            session_factory=self._build_session_factory(self._kernel),
        )

    def _build_session_factory(self, kernel: KernelInterface) -> Any:
        if kernel.container.enabled:

            def _docker_factory(
                session_id: str,
                kernel_name: str,
                working_directory: str | None = None,
                sandbox: SandboxConfig | None = None,
            ) -> DockerKernelSession:
                return DockerKernelSession(
                    session_id,
                    kernel_name,
                    policy=kernel.container,
                    startup_timeout=kernel.startup_timeout_seconds,
                    working_directory=working_directory,
                    sandbox=sandbox,
                )

            return _docker_factory

        def _local_factory(
            session_id: str,
            kernel_name: str,
            working_directory: str | None = None,
            sandbox: SandboxConfig | None = None,
        ) -> KernelSession:
            del working_directory, sandbox
            return KernelSession(
                session_id,
                kernel_name,
                startup_timeout=kernel.startup_timeout_seconds,
            )

        return _local_factory

    async def execute(self, contract: ExecutionContract) -> ExecutionResult:
        """Execute code in a local or Docker-backed kernel session."""
        code = contract.inputs.stdin or ""
        if not code.strip():
            return ExecutionResult(
                execution_id=contract.execution_id,
                success=False,
                error="Kernel execution requires code in inputs.stdin",
            )

        language = str(
            contract.metadata.get("language")
            or contract.inputs.command
            or self._kernel.kernel_name
            or "python"
        )
        kernel_name = _language_to_kernel(language)
        session_id = contract.metadata.get("session_id")
        effective_session_id = (
            str(session_id) if session_id is not None else f"oneshot-{uuid.uuid4().hex[:12]}"
        )
        timeout = min(
            self._kernel.execution_timeout_seconds,
            contract.sandbox.timeout_ms / 1000.0,
        )
        working_directory = contract.inputs.working_directory
        if kernel_name == "python3":
            if self._kernel.container.enabled and self._kernel.container.mount_working_directory:
                code = _build_directory_preamble(code, self._kernel.container.container_workdir)
            else:
                code = _build_directory_preamble(code, working_directory)

        try:
            session = await self._session_manager.get_or_create(
                effective_session_id,
                kernel_name,
                working_directory=working_directory,
                sandbox=contract.sandbox,
            )
            success, stdout, stderr, artifacts = await session.execute(code, timeout)

            if session_id is None:
                await self._session_manager.remove(effective_session_id)

            return ExecutionResult(
                execution_id=contract.execution_id,
                success=success,
                exit_code=0 if success else 1,
                stdout=stdout,
                stderr=stderr,
                artifacts=artifacts,
                metadata={
                    "session_id": session_id,
                    "effective_session_id": effective_session_id,
                    "kernel_name": kernel_name,
                    "backend": "docker" if self._kernel.container.enabled else "local",
                },
            )
        except Exception as exc:
            logger.exception("jupyter_execution_failed adapter_id=%s", self.adapter_id)
            return ExecutionResult(
                execution_id=contract.execution_id,
                success=False,
                exit_code=1,
                error=str(exc),
                stderr=str(exc),
                metadata={
                    "session_id": session_id,
                    "effective_session_id": effective_session_id,
                    "kernel_name": kernel_name,
                    "backend": "docker" if self._kernel.container.enabled else "local",
                },
            )

    async def shutdown(self) -> None:
        """Shutdown all managed kernel sessions."""
        await self._session_manager.shutdown_all()


def build_default_jupyter_definition(
    *,
    adapter_id: str,
    tool_id: str,
    kernel_name: str = "python3",
    max_sessions: int = 10,
    idle_timeout_seconds: float = 300.0,
    startup_timeout_seconds: float = 30.0,
    execution_timeout_seconds: float = 60.0,
    docker_enabled: bool = False,
    docker_image: str = "quay.io/jupyter/minimal-notebook:python-3.11",
    docker_allowed_images: list[str] | None = None,
    docker_network_enabled: bool = False,
    docker_mount_working_directory: bool = True,
    docker_container_workdir: str = "/workspace",
) -> AdapterDefinition:
    """Build a default adapter definition for runtime registration."""
    return AdapterDefinition(
        adapter_id=adapter_id,
        name="jupyter-kernel",
        tool_id=tool_id,
        type=AdapterType.KERNEL,
        kernel=KernelInterface(
            kernel_name=kernel_name,
            max_sessions=max_sessions,
            idle_timeout_seconds=idle_timeout_seconds,
            startup_timeout_seconds=startup_timeout_seconds,
            execution_timeout_seconds=execution_timeout_seconds,
            container=KernelContainerPolicy(
                enabled=docker_enabled,
                image=docker_image,
                allowed_images=docker_allowed_images or [],
                network_enabled=docker_network_enabled,
                mount_working_directory=docker_mount_working_directory,
                container_workdir=docker_container_workdir,
            ),
        ),
        sandbox_override={
            "network": {"enabled": docker_network_enabled},
        },
        metadata={
            "backend": "docker" if docker_enabled else "local",
        },
    )
