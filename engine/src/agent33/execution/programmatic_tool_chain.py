"""Programmatic Tool Calling (PTC) execution engine.

Allows LLM-generated Python scripts to call registered tools via a
TCP localhost RPC socket, collapsing N LLM inference turns into a single
script execution.  The parent process spawns a child subprocess that runs
the script, and tool calls travel over the socket back to the parent for
dispatch through the tool registry.

Phase 56 of the Hermes Adoption Roadmap.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
import os
import secrets
import socket
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent33.tools.base import ToolContext
    from agent33.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT_S = 300
_DEFAULT_MAX_CALLS = 50
_DEFAULT_MAX_STDOUT_BYTES = 50 * 1024  # 50 KB

# Modules the child script is allowed to import.
_ALLOWED_IMPORTS: frozenset[str] = frozenset(
    {
        "json",
        "re",
        "math",
        "datetime",
        "time",
        "os.path",
        "pathlib",
        "collections",
        "itertools",
        "functools",
        "textwrap",
        "string",
        "hashlib",
        "base64",
        "urllib.parse",
        "typing",
        "dataclasses",
        "enum",
        "copy",
        "io",
        "csv",
        "agent33_tools",
    }
)

# Built-in functions / names that must not be called or accessed.
# "open" is blocked because file access should go through the file_ops tool,
# not the built-in open().  Blocking the *name* (not just the call) prevents
# aliasing bypasses such as ``f = open; f("/etc/passwd")``.
_BLOCKED_NAMES: frozenset[str] = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "__import__",
        "globals",
        "locals",
        "breakpoint",
        "exit",
        "quit",
        "open",
    }
)

# Attribute names that indicate sandbox escape attempts.
_BLOCKED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "__builtins__",
        "__subclasses__",
        "__bases__",
        "__mro__",
        "__class__",
        "__globals__",
        "__code__",
    }
)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PTCResult:
    """Outcome of a PTC script execution."""

    success: bool
    stdout: str = ""
    stderr: str = ""
    tool_calls_made: int = 0
    elapsed_s: float = 0.0
    error: str = ""


@dataclass(slots=True)
class _RPCState:
    """Mutable state shared across RPC handler coroutines."""

    call_count: int = 0
    tool_results: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# AST validation
# ---------------------------------------------------------------------------


class _ASTValidator(ast.NodeVisitor):
    """Walk the AST of an LLM-generated script and reject unsafe patterns."""

    def __init__(self, allowed_imports: frozenset[str] | None = None) -> None:
        self.violations: list[str] = []
        self._allowed_imports = allowed_imports or _ALLOWED_IMPORTS

    # -- Imports -----------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name not in self._allowed_imports:
                self.violations.append(f"Blocked import: '{alias.name}' (line {node.lineno})")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        # Allow importing from allowed modules or their sub-modules.
        if not any(
            module == allowed or module.startswith(allowed + ".")
            for allowed in self._allowed_imports
        ):
            self.violations.append(f"Blocked import from: '{module}' (line {node.lineno})")
        self.generic_visit(node)

    # -- Blocked built-in calls -------------------------------------------

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _BLOCKED_NAMES:
            self.violations.append(f"Blocked name: '{node.id}' (line {node.lineno})")
        self.generic_visit(node)

    # -- Blocked attribute access -----------------------------------------

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in _BLOCKED_ATTRIBUTES:
            self.violations.append(
                f"Blocked attribute access: '.{node.attr}' (line {node.lineno})"
            )
        self.generic_visit(node)

    # -- open() is blocked (defence-in-depth; visit_Name also catches it) --

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            self.violations.append(f"Blocked call to 'open()' (line {node.lineno})")
        self.generic_visit(node)


def validate_code_ast(
    code: str,
    allowed_imports: frozenset[str] | None = None,
) -> list[str]:
    """Parse *code* and return a list of AST-level violations.

    Returns an empty list if the code passes validation.
    Raises ``SyntaxError`` if the code cannot be parsed.
    """
    tree = ast.parse(code, mode="exec")
    validator = _ASTValidator(allowed_imports)
    validator.visit(tree)
    return validator.violations


# ---------------------------------------------------------------------------
# Stub module generation
# ---------------------------------------------------------------------------


def generate_stubs(
    allowed_tools: list[str],
    rpc_host: str,
    rpc_port: int,
    secret: str,
) -> str:
    """Generate Python source for the ``agent33_tools`` stub module.

    Each allowed tool becomes a function that sends an RPC call to the
    parent's TCP socket server and returns the result.
    """
    tool_functions = []
    for tool_name in sorted(allowed_tools):
        safe_name = tool_name.replace("-", "_")
        tool_functions.append(
            textwrap.dedent(f"""\
            def {safe_name}(**params):
                \"\"\"Call the '{tool_name}' tool via RPC.\"\"\"
                return _rpc_call("{tool_name}", params)
            """)
        )

    source = textwrap.dedent(f"""\
        \"\"\"Auto-generated tool stubs for PTC execution.\"\"\"
        import json
        import socket

        _RPC_HOST = {rpc_host!r}
        _RPC_PORT = {rpc_port}
        _SECRET = {secret!r}


        def _rpc_call(tool_name, params):
            \"\"\"Send an RPC request to the parent process and return the result.\"\"\"
            request = json.dumps({{
                "secret": _SECRET,
                "tool": tool_name,
                "params": params,
            }})
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.connect((_RPC_HOST, _RPC_PORT))
                sock.sendall(request.encode("utf-8"))
                sock.shutdown(socket.SHUT_WR)
                chunks = []
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                response = json.loads(b"".join(chunks).decode("utf-8"))
                if not response.get("success", False):
                    raise RuntimeError(
                        f"Tool '{{tool_name}}' failed: {{response.get('error', 'unknown')}}"
                    )
                return response.get("output", "")
            finally:
                sock.close()

    """)
    source += "\n".join(tool_functions)
    return source


# ---------------------------------------------------------------------------
# PTCExecutor
# ---------------------------------------------------------------------------


class PTCExecutor:
    """Execute LLM-generated Python scripts with tool-calling via RPC.

    The executor:
    1. Validates the script via AST analysis.
    2. Generates a stub module with RPC functions for allowed tools.
    3. Starts a TCP localhost RPC server.
    4. Spawns a subprocess that runs the script.
    5. Dispatches tool calls from the child through the tool registry.
    6. Returns the script's stdout plus execution metadata.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        allowed_tools: list[str] | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_calls: int = _DEFAULT_MAX_CALLS,
        max_stdout_bytes: int = _DEFAULT_MAX_STDOUT_BYTES,
    ) -> None:
        self._tool_registry = tool_registry
        self._allowed_tools = allowed_tools or [
            "web_search",
            "web_extract",
            "read_file",
            "write_file",
            "search_files",
            "patch",
            "shell",
        ]
        self._timeout_s = timeout_s
        self._max_calls = max_calls
        self._max_stdout_bytes = max_stdout_bytes

    async def execute(
        self,
        code: str,
        context: ToolContext | None = None,
    ) -> PTCResult:
        """Validate and execute *code* in an isolated subprocess.

        Tool calls inside the script are dispatched through the tool
        registry via a TCP localhost RPC server.
        """
        start = time.monotonic()

        # 1. AST validation
        try:
            violations = validate_code_ast(code)
        except SyntaxError as exc:
            return PTCResult(
                success=False,
                error=f"Syntax error in script: {exc}",
                elapsed_s=time.monotonic() - start,
            )

        if violations:
            return PTCResult(
                success=False,
                error=f"AST validation failed: {'; '.join(violations)}",
                elapsed_s=time.monotonic() - start,
            )

        # 2. Generate shared secret
        request_secret = secrets.token_hex(16)

        # 3. Start RPC server on an ephemeral port
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(("127.0.0.1", 0))
        server_sock.listen(self._max_calls + 5)
        server_sock.setblocking(False)
        _, rpc_port = server_sock.getsockname()

        # 4. Generate stubs module
        stubs_source = generate_stubs(self._allowed_tools, "127.0.0.1", rpc_port, request_secret)

        # 5. Write temp files
        tmp_dir = tempfile.mkdtemp(prefix="ptc_")
        stubs_path = Path(tmp_dir) / "agent33_tools.py"
        main_path = Path(tmp_dir) / "main.py"
        stubs_path.write_text(stubs_source, encoding="utf-8")
        main_path.write_text(code, encoding="utf-8")

        rpc_state = _RPCState()

        # Import ToolContext here to construct a default if needed
        from agent33.tools.base import ToolContext as ToolCtx

        tool_context = context or ToolCtx()

        try:
            result = await asyncio.wait_for(
                self._run_with_rpc(
                    server_sock,
                    request_secret,
                    rpc_state,
                    tmp_dir,
                    main_path,
                    tool_context,
                ),
                timeout=self._timeout_s,
            )
            return PTCResult(
                success=result["success"],
                stdout=result["stdout"],
                stderr=result["stderr"],
                tool_calls_made=rpc_state.call_count,
                elapsed_s=time.monotonic() - start,
                error=result.get("error", ""),
            )
        except TimeoutError:
            return PTCResult(
                success=False,
                error=f"PTC execution timed out after {self._timeout_s}s",
                tool_calls_made=rpc_state.call_count,
                elapsed_s=time.monotonic() - start,
            )
        except Exception as exc:
            return PTCResult(
                success=False,
                error=f"PTC execution error: {exc}",
                tool_calls_made=rpc_state.call_count,
                elapsed_s=time.monotonic() - start,
            )
        finally:
            server_sock.close()
            # Clean up temp files
            try:
                stubs_path.unlink(missing_ok=True)
                main_path.unlink(missing_ok=True)
                Path(tmp_dir).rmdir()
            except OSError:
                pass

    async def _run_with_rpc(
        self,
        server_sock: socket.socket,
        secret: str,
        state: _RPCState,
        tmp_dir: str,
        main_path: Path,
        context: ToolContext,
    ) -> dict[str, Any]:
        """Spawn the child process and handle RPC calls concurrently."""
        loop = asyncio.get_running_loop()

        # Spawn child subprocess
        env = {**os.environ, "PYTHONPATH": tmp_dir}
        python_exe = sys.executable

        proc = await asyncio.create_subprocess_exec(
            python_exe,
            "-u",
            str(main_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # Run the RPC server and the subprocess concurrently
        rpc_task = asyncio.ensure_future(
            self._serve_rpc(loop, server_sock, secret, state, context)
        )

        stdout_bytes, stderr_bytes = await proc.communicate()

        # Give a brief window for any in-flight RPC calls to finish
        rpc_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await rpc_task

        # Truncate stdout if needed
        truncated = False
        if len(stdout_bytes) > self._max_stdout_bytes:
            stdout_bytes = stdout_bytes[: self._max_stdout_bytes]
            truncated = True

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if truncated:
            stdout += "\n[OUTPUT TRUNCATED]"

        exit_code = proc.returncode if proc.returncode is not None else -1

        if exit_code != 0:
            return {
                "success": False,
                "stdout": stdout,
                "stderr": stderr,
                "error": f"Script exited with code {exit_code}: {stderr[:500]}",
            }

        return {
            "success": True,
            "stdout": stdout,
            "stderr": stderr,
        }

    async def _serve_rpc(
        self,
        loop: asyncio.AbstractEventLoop,
        server_sock: socket.socket,
        secret: str,
        state: _RPCState,
        context: ToolContext,
    ) -> None:
        """Accept incoming RPC connections and dispatch tool calls."""
        while True:
            try:
                client_sock, _ = await loop.sock_accept(server_sock)
            except (OSError, asyncio.CancelledError):
                break

            # Handle each connection in its own task to avoid blocking
            asyncio.ensure_future(self._handle_rpc_connection(client_sock, secret, state, context))

    async def _handle_rpc_connection(
        self,
        client_sock: socket.socket,
        secret: str,
        state: _RPCState,
        context: ToolContext,
    ) -> None:
        """Handle a single RPC connection from the child process."""
        loop = asyncio.get_running_loop()
        try:
            client_sock.setblocking(False)
            # Read the full request
            chunks: list[bytes] = []
            while True:
                try:
                    chunk = await loop.sock_recv(client_sock, 4096)
                except (ConnectionResetError, OSError):
                    break
                if not chunk:
                    break
                chunks.append(chunk)

            raw = b"".join(chunks).decode("utf-8", errors="replace")
            if not raw:
                return

            try:
                request = json.loads(raw)
            except json.JSONDecodeError:
                response = {"success": False, "error": "Invalid JSON request"}
                await loop.sock_sendall(
                    client_sock,
                    json.dumps(response).encode("utf-8"),
                )
                return

            # Authenticate
            if request.get("secret") != secret:
                response = {"success": False, "error": "Authentication failed"}
                await loop.sock_sendall(
                    client_sock,
                    json.dumps(response).encode("utf-8"),
                )
                return

            # Check call limit
            if state.call_count >= self._max_calls:
                response = {
                    "success": False,
                    "error": f"Tool call limit exceeded ({self._max_calls})",
                }
                await loop.sock_sendall(
                    client_sock,
                    json.dumps(response).encode("utf-8"),
                )
                return

            tool_name = request.get("tool", "")
            params = request.get("params", {})

            # Validate tool is allowed
            if tool_name not in self._allowed_tools:
                response = {
                    "success": False,
                    "error": f"Tool '{tool_name}' is not in the allowed PTC tools",
                }
                await loop.sock_sendall(
                    client_sock,
                    json.dumps(response).encode("utf-8"),
                )
                return

            # Dispatch through tool registry
            state.call_count += 1
            tool = self._tool_registry.get(tool_name)
            if tool is None:
                response = {
                    "success": False,
                    "error": f"Tool '{tool_name}' not found in registry",
                }
            else:
                try:
                    tool_result = await tool.execute(params, context)
                    response = {
                        "success": tool_result.success,
                        "output": tool_result.output,
                        "error": tool_result.error,
                    }
                except Exception as exc:
                    response = {
                        "success": False,
                        "error": f"Tool execution error: {exc}",
                    }

            state.tool_results.append({"tool": tool_name, "params": params, "result": response})

            await loop.sock_sendall(
                client_sock,
                json.dumps(response).encode("utf-8"),
            )
        except (asyncio.CancelledError, OSError):
            pass
        finally:
            client_sock.close()
