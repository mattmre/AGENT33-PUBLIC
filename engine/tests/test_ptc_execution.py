"""Tests for Phase 56 — Programmatic Tool Calling (PTC) execution.

Covers:
- AST validation (blocked imports, blocked builtins, open() calls)
- Stub module generation (valid Python, RPC connection info)
- RPC round-trip (tool call dispatched through registry, result returned)
- Resource limits (timeout, max_calls, stdout truncation)
- Multi-tool scripts
- PTCExecuteTool (SchemaAwareTool protocol)
- Config defaults (ptc_enabled, ptc_timeout_s, etc.)
- PTCExecuteTool construction and metadata
"""

from __future__ import annotations

import ast
import textwrap
from typing import Any

import pytest

from agent33.config import Settings
from agent33.execution.programmatic_tool_chain import (
    PTCExecutor,
    PTCResult,
    generate_stubs,
    validate_code_ast,
)
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.builtin.ptc_execute import PTCExecuteTool
from agent33.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeTool:
    """Minimal tool that records calls and returns configurable output."""

    def __init__(self, name: str, output: str = "ok") -> None:
        self._name = name
        self._output = output
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Fake tool: {self._name}"

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        self.calls.append(params)
        return ToolResult.ok(self._output)


class FailingTool:
    """Tool that always fails."""

    @property
    def name(self) -> str:
        return "fail_tool"

    @property
    def description(self) -> str:
        return "Always fails"

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.fail("intentional failure")


@pytest.fixture()
def registry_with_tools() -> tuple[ToolRegistry, dict[str, FakeTool]]:
    """Create a ToolRegistry with several fake tools registered."""
    registry = ToolRegistry()
    tools: dict[str, FakeTool] = {}
    for name in ("shell", "read_file", "write_file", "search_files"):
        tool = FakeTool(name, output=f"{name}_result")
        registry.register(tool)
        tools[name] = tool
    return registry, tools


# ===================================================================
# AST Validation
# ===================================================================


class TestASTValidation:
    """Tests for validate_code_ast and the _ASTValidator walker."""

    def test_safe_code_passes(self) -> None:
        code = textwrap.dedent("""\
            import json
            import agent33_tools
            result = agent33_tools.shell(command="echo hello")
            print(result)
        """)
        violations = validate_code_ast(code)
        assert violations == []

    def test_blocked_import_os(self) -> None:
        code = "import os"
        violations = validate_code_ast(code)
        assert len(violations) == 1
        assert "Blocked import: 'os'" in violations[0]

    def test_blocked_import_subprocess(self) -> None:
        code = "import subprocess"
        violations = validate_code_ast(code)
        assert len(violations) == 1
        assert "Blocked import: 'subprocess'" in violations[0]

    def test_blocked_import_from_os(self) -> None:
        code = "from os import system"
        violations = validate_code_ast(code)
        assert len(violations) == 1
        assert "Blocked import from: 'os'" in violations[0]

    def test_os_path_allowed(self) -> None:
        """os.path is explicitly in the allowed imports list."""
        code = "import os.path"
        violations = validate_code_ast(code)
        assert violations == []

    def test_blocked_exec_call(self) -> None:
        code = 'exec("print(1)")'
        violations = validate_code_ast(code)
        assert any("Blocked name: 'exec'" in v for v in violations)

    def test_blocked_eval_call(self) -> None:
        code = 'eval("1+1")'
        violations = validate_code_ast(code)
        assert any("Blocked name: 'eval'" in v for v in violations)

    def test_blocked_compile(self) -> None:
        code = 'compile("pass", "<string>", "exec")'
        violations = validate_code_ast(code)
        assert any("Blocked name: 'compile'" in v for v in violations)

    def test_blocked_dunder_import(self) -> None:
        code = '__import__("os")'
        violations = validate_code_ast(code)
        assert any("__import__" in v for v in violations)

    def test_blocked_builtins_attribute(self) -> None:
        code = "x = obj.__builtins__"
        violations = validate_code_ast(code)
        assert any("__builtins__" in v for v in violations)

    def test_blocked_subclasses_attribute(self) -> None:
        code = "x = str.__subclasses__()"
        violations = validate_code_ast(code)
        assert any("__subclasses__" in v for v in violations)

    def test_blocked_open_call(self) -> None:
        code = 'f = open("/etc/passwd")'
        violations = validate_code_ast(code)
        assert any("open" in v for v in violations)

    def test_blocked_open_name_alias(self) -> None:
        """Assigning open to an alias must be blocked at the name level.

        Without 'open' in _BLOCKED_NAMES, ``reader = open`` would pass AST
        validation because visit_Call only fires on direct ``open(...)``
        calls, not on bare name references.  File access should go through
        the file_ops tool.
        """
        code = "reader = open"
        violations = validate_code_ast(code)
        assert len(violations) >= 1
        assert any("open" in v for v in violations)

    def test_syntax_error_raises(self) -> None:
        with pytest.raises(SyntaxError):
            validate_code_ast("def foo(")

    def test_allowed_stdlib_imports(self) -> None:
        code = textwrap.dedent("""\
            import json
            import re
            import math
            import datetime
            import collections
            import itertools
            import functools
            import hashlib
            import base64
            import typing
        """)
        violations = validate_code_ast(code)
        assert violations == []

    def test_multiple_violations_collected(self) -> None:
        code = textwrap.dedent("""\
            import os
            import subprocess
            exec("pass")
        """)
        violations = validate_code_ast(code)
        assert len(violations) == 3

    def test_import_from_submodule_of_allowed(self) -> None:
        """from urllib.parse import urlparse should be allowed."""
        code = "from urllib.parse import urlparse"
        violations = validate_code_ast(code)
        assert violations == []

    def test_import_socket_blocked(self) -> None:
        """Direct socket import is blocked (child must use stubs only)."""
        code = "import socket"
        violations = validate_code_ast(code)
        assert len(violations) == 1


# ===================================================================
# Stub Generation
# ===================================================================


class TestStubGeneration:
    """Tests for generate_stubs()."""

    def test_generates_valid_python(self) -> None:
        source = generate_stubs(["shell", "read_file"], "127.0.0.1", 12345, "test-secret")
        # Must parse without errors
        tree = ast.parse(source)
        assert tree is not None

    def test_contains_tool_functions(self) -> None:
        source = generate_stubs(["shell", "read_file", "web_fetch"], "127.0.0.1", 9999, "s")
        assert "def shell(" in source
        assert "def read_file(" in source
        assert "def web_fetch(" in source

    def test_embeds_rpc_connection_info(self) -> None:
        source = generate_stubs(["shell"], "127.0.0.1", 54321, "my-secret-token")
        assert "_RPC_HOST = '127.0.0.1'" in source
        assert "_RPC_PORT = 54321" in source
        assert "_SECRET = 'my-secret-token'" in source

    def test_hyphenated_tool_names_converted(self) -> None:
        source = generate_stubs(["web-fetch"], "127.0.0.1", 9999, "s")
        # Python function names cannot contain hyphens
        assert "def web_fetch(" in source
        # But the RPC call uses the original name
        assert "'web-fetch'" in source

    def test_contains_rpc_call_helper(self) -> None:
        source = generate_stubs(["shell"], "127.0.0.1", 9999, "s")
        assert "def _rpc_call(" in source
        assert "socket.socket" in source

    def test_sorted_tool_order(self) -> None:
        source = generate_stubs(["write_file", "read_file", "shell"], "127.0.0.1", 9999, "s")
        # Functions should appear in sorted order
        read_pos = source.index("def read_file(")
        shell_pos = source.index("def shell(")
        write_pos = source.index("def write_file(")
        assert read_pos < shell_pos < write_pos


# ===================================================================
# PTCExecutor — Integration (subprocess + RPC)
# ===================================================================


class TestPTCExecutor:
    """Integration tests for PTCExecutor that actually spawn subprocesses."""

    @pytest.fixture()
    def executor(
        self, registry_with_tools: tuple[ToolRegistry, dict[str, FakeTool]]
    ) -> PTCExecutor:
        registry, _ = registry_with_tools
        return PTCExecutor(
            tool_registry=registry,
            allowed_tools=["shell", "read_file", "write_file", "search_files"],
            timeout_s=30,
            max_calls=50,
        )

    async def test_simple_print_script(self, executor: PTCExecutor) -> None:
        """A script that just prints should succeed without tool calls."""
        result = await executor.execute('print("hello from ptc")')
        assert result.success is True
        assert "hello from ptc" in result.stdout
        assert result.tool_calls_made == 0

    async def test_tool_call_round_trip(
        self,
        registry_with_tools: tuple[ToolRegistry, dict[str, FakeTool]],
    ) -> None:
        """Script calls a tool via RPC and gets the result back."""
        registry, tools = registry_with_tools
        executor = PTCExecutor(
            tool_registry=registry,
            allowed_tools=["shell"],
            timeout_s=30,
        )

        code = textwrap.dedent("""\
            import agent33_tools
            result = agent33_tools.shell(command="echo test")
            print(f"got: {result}")
        """)
        result = await executor.execute(code)
        assert result.success is True
        assert "got: shell_result" in result.stdout
        assert result.tool_calls_made == 1
        assert len(tools["shell"].calls) == 1
        assert tools["shell"].calls[0]["command"] == "echo test"

    async def test_multiple_tool_calls(
        self,
        registry_with_tools: tuple[ToolRegistry, dict[str, FakeTool]],
    ) -> None:
        """Script calls multiple different tools sequentially."""
        registry, tools = registry_with_tools
        executor = PTCExecutor(
            tool_registry=registry,
            allowed_tools=["shell", "read_file", "search_files"],
            timeout_s=30,
        )

        code = textwrap.dedent("""\
            import agent33_tools
            r1 = agent33_tools.shell(command="ls")
            r2 = agent33_tools.read_file(path="/tmp/test.txt")
            r3 = agent33_tools.search_files(pattern="*.py")
            print(f"{r1}|{r2}|{r3}")
        """)
        result = await executor.execute(code)
        assert result.success is True
        assert result.tool_calls_made == 3
        assert "shell_result" in result.stdout
        assert "read_file_result" in result.stdout
        assert "search_files_result" in result.stdout

    async def test_ast_validation_rejects_unsafe_code(self, executor: PTCExecutor) -> None:
        """Script with blocked imports is rejected before execution."""
        code = textwrap.dedent("""\
            import os
            os.system("rm -rf /")
        """)
        result = await executor.execute(code)
        assert result.success is False
        assert "AST validation failed" in result.error
        assert "Blocked import" in result.error
        assert result.tool_calls_made == 0

    async def test_syntax_error_rejected(self, executor: PTCExecutor) -> None:
        result = await executor.execute("def foo(")
        assert result.success is False
        assert "Syntax error" in result.error

    async def test_script_runtime_error(self, executor: PTCExecutor) -> None:
        """A script that raises at runtime returns success=False."""
        code = 'raise ValueError("boom")'
        result = await executor.execute(code)
        assert result.success is False
        assert result.tool_calls_made == 0

    async def test_timeout_enforced(
        self,
        registry_with_tools: tuple[ToolRegistry, dict[str, FakeTool]],
    ) -> None:
        """Script that runs too long is terminated."""
        registry, _ = registry_with_tools
        executor = PTCExecutor(
            tool_registry=registry,
            allowed_tools=["shell"],
            timeout_s=2,
        )

        code = textwrap.dedent("""\
            import time
            time.sleep(60)
        """)
        result = await executor.execute(code)
        assert result.success is False
        assert "timed out" in result.error

    async def test_stdout_truncation(
        self,
        registry_with_tools: tuple[ToolRegistry, dict[str, FakeTool]],
    ) -> None:
        """Stdout exceeding max_stdout_bytes is truncated."""
        registry, _ = registry_with_tools
        executor = PTCExecutor(
            tool_registry=registry,
            allowed_tools=["shell"],
            timeout_s=30,
            max_stdout_bytes=100,
        )

        code = 'print("x" * 500)'
        result = await executor.execute(code)
        assert result.success is True
        assert "[OUTPUT TRUNCATED]" in result.stdout
        # Stdout before truncation message should be <= max_stdout_bytes
        assert len(result.stdout.encode("utf-8")) < 200

    async def test_max_calls_limit(
        self,
        registry_with_tools: tuple[ToolRegistry, dict[str, FakeTool]],
    ) -> None:
        """Script exceeding max_calls gets an error from the RPC server."""
        registry, _ = registry_with_tools
        executor = PTCExecutor(
            tool_registry=registry,
            allowed_tools=["shell"],
            timeout_s=30,
            max_calls=3,
        )

        code = textwrap.dedent("""\
            import agent33_tools
            results = []
            for i in range(5):
                try:
                    r = agent33_tools.shell(command=f"echo {i}")
                    results.append(r)
                except RuntimeError as e:
                    results.append(f"ERROR: {e}")
            print("|".join(str(r) for r in results))
        """)
        result = await executor.execute(code)
        # Script should complete (it catches the error), but some calls fail
        assert result.tool_calls_made == 3
        assert "limit exceeded" in result.stdout.lower() or "error" in result.stdout.lower()

    async def test_disallowed_tool_not_available(
        self,
        registry_with_tools: tuple[ToolRegistry, dict[str, FakeTool]],
    ) -> None:
        """Tools not in allowed_tools have no stub function generated.

        The child script gets an AttributeError when trying to call a
        tool that was not included in the allowed list, because the stub
        module simply does not define it.
        """
        registry, _ = registry_with_tools
        # Only allow "shell", not "read_file"
        executor = PTCExecutor(
            tool_registry=registry,
            allowed_tools=["shell"],
            timeout_s=30,
        )

        code = textwrap.dedent("""\
            import agent33_tools
            try:
                r = agent33_tools.read_file(path="/tmp/x")
                print(f"got: {r}")
            except AttributeError as e:
                print(f"blocked: {e}")
        """)
        result = await executor.execute(code)
        # The function doesn't exist in the stubs, so AttributeError is raised
        assert "blocked" in result.stdout.lower()

    async def test_unregistered_tool_returns_error(self) -> None:
        """Calling a tool that is allowed but not registered returns an error."""
        registry = ToolRegistry()
        executor = PTCExecutor(
            tool_registry=registry,
            allowed_tools=["nonexistent_tool"],
            timeout_s=30,
        )

        code = textwrap.dedent("""\
            import agent33_tools
            try:
                r = agent33_tools.nonexistent_tool(x=1)
                print(f"got: {r}")
            except RuntimeError as e:
                print(f"error: {e}")
        """)
        result = await executor.execute(code)
        assert "not found" in result.stdout.lower()

    async def test_tool_failure_propagated(self) -> None:
        """When a tool returns ToolResult.fail, the child gets a RuntimeError."""
        registry = ToolRegistry()
        registry.register(FailingTool())
        executor = PTCExecutor(
            tool_registry=registry,
            allowed_tools=["fail_tool"],
            timeout_s=30,
        )

        code = textwrap.dedent("""\
            import agent33_tools
            try:
                r = agent33_tools.fail_tool()
                print(f"got: {r}")
            except RuntimeError as e:
                print(f"failed: {e}")
        """)
        result = await executor.execute(code)
        assert result.tool_calls_made == 1
        assert "failed" in result.stdout.lower()
        assert "intentional failure" in result.stdout.lower()


# ===================================================================
# PTCExecuteTool (SchemaAwareTool)
# ===================================================================


class TestPTCExecuteTool:
    """Tests for the PTCExecuteTool wrapper."""

    @pytest.fixture()
    def tool(
        self, registry_with_tools: tuple[ToolRegistry, dict[str, FakeTool]]
    ) -> PTCExecuteTool:
        registry, _ = registry_with_tools
        return PTCExecuteTool(
            tool_registry=registry,
            allowed_tools=["shell", "read_file"],
            timeout_s=30,
        )

    def test_tool_name(self, tool: PTCExecuteTool) -> None:
        assert tool.name == "ptc_execute"

    def test_tool_description(self, tool: PTCExecuteTool) -> None:
        assert "Python script" in tool.description

    def test_parameters_schema(self, tool: PTCExecuteTool) -> None:
        schema = tool.parameters_schema
        assert schema["type"] == "object"
        assert "code" in schema["properties"]
        assert "code" in schema["required"]

    async def test_empty_code_rejected(self, tool: PTCExecuteTool) -> None:
        result = await tool.execute({"code": ""}, ToolContext())
        assert result.success is False
        assert "No code" in result.error

    async def test_missing_code_rejected(self, tool: PTCExecuteTool) -> None:
        result = await tool.execute({}, ToolContext())
        assert result.success is False
        assert "No code" in result.error

    async def test_unsafe_code_rejected(self, tool: PTCExecuteTool) -> None:
        result = await tool.execute(
            {"code": "import subprocess\nsubprocess.run(['ls'])"},
            ToolContext(),
        )
        assert result.success is False
        assert "safety validation failed" in result.error.lower()

    async def test_syntax_error_rejected(self, tool: PTCExecuteTool) -> None:
        result = await tool.execute(
            {"code": "def foo("},
            ToolContext(),
        )
        assert result.success is False
        assert "Syntax error" in result.error

    async def test_successful_execution(self, tool: PTCExecuteTool) -> None:
        result = await tool.execute(
            {"code": 'print("ptc works")'},
            ToolContext(),
        )
        assert result.success is True
        assert "ptc works" in result.output

    async def test_tool_call_via_execute(
        self,
        registry_with_tools: tuple[ToolRegistry, dict[str, FakeTool]],
    ) -> None:
        """End-to-end: tool execute -> PTCExecutor -> child -> RPC -> tool."""
        registry, tools = registry_with_tools
        ptc_tool = PTCExecuteTool(
            tool_registry=registry,
            allowed_tools=["shell"],
            timeout_s=30,
        )

        code = textwrap.dedent("""\
            import agent33_tools
            result = agent33_tools.shell(command="whoami")
            print(result)
        """)
        result = await ptc_tool.execute({"code": code}, ToolContext())
        assert result.success is True
        assert "shell_result" in result.output
        assert len(tools["shell"].calls) == 1

    async def test_schema_aware_protocol(self, tool: PTCExecuteTool) -> None:
        """Verify the tool satisfies SchemaAwareTool protocol checks."""
        from agent33.tools.base import SchemaAwareTool

        assert isinstance(tool, SchemaAwareTool)


# ===================================================================
# PTCResult model
# ===================================================================


class TestPTCResult:
    """Tests for the PTCResult dataclass."""

    def test_default_values(self) -> None:
        r = PTCResult(success=True)
        assert r.stdout == ""
        assert r.stderr == ""
        assert r.tool_calls_made == 0
        assert r.elapsed_s == 0.0
        assert r.error == ""

    def test_immutable(self) -> None:
        r = PTCResult(success=True, stdout="hello")
        with pytest.raises(AttributeError):
            r.stdout = "changed"  # type: ignore[misc]


# ===================================================================
# Config Defaults (Phase 56 wiring)
# ===================================================================


class TestPTCConfigDefaults:
    """Verify PTC config fields exist with correct defaults."""

    def test_ptc_enabled_default(self) -> None:
        s = Settings()
        assert s.ptc_enabled is True

    def test_ptc_timeout_s_default(self) -> None:
        s = Settings()
        assert s.ptc_timeout_s == 300

    def test_ptc_max_calls_default(self) -> None:
        s = Settings()
        assert s.ptc_max_calls == 50

    def test_ptc_max_stdout_bytes_default(self) -> None:
        s = Settings()
        assert s.ptc_max_stdout_bytes == 51200

    def test_ptc_allowed_tools_default_empty(self) -> None:
        s = Settings()
        assert s.ptc_allowed_tools == ""


# ===================================================================
# PTCExecuteTool construction metadata (Phase 56 wiring)
# ===================================================================


class TestPTCExecuteToolConstruction:
    """Verify PTCExecuteTool can be constructed and has correct metadata."""

    def test_construction_with_defaults(self) -> None:
        registry = ToolRegistry()
        tool = PTCExecuteTool(tool_registry=registry)
        assert tool.name == "ptc_execute"
        assert "code" in tool.parameters_schema["properties"]
        assert "code" in tool.parameters_schema["required"]

    def test_construction_with_custom_allowed_tools(self) -> None:
        registry = ToolRegistry()
        tool = PTCExecuteTool(
            tool_registry=registry,
            allowed_tools=["shell", "read_file"],
            timeout_s=60.0,
            max_calls=10,
            max_stdout_bytes=1024,
        )
        assert tool.name == "ptc_execute"
        assert "Python script" in tool.description
