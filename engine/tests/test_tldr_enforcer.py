"""Tests for agent33.tools.tldr_enforcer — TLDR AST snapshot and tool."""

from __future__ import annotations

import textwrap

import pytest

from agent33.tools.base import ToolContext
from agent33.tools.tldr_enforcer import TLDRReadEnforcerTool, create_tldr_snapshot

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tool() -> TLDRReadEnforcerTool:
    return TLDRReadEnforcerTool()


@pytest.fixture
def context() -> ToolContext:
    return ToolContext()


# ---------------------------------------------------------------------------
# create_tldr_snapshot — core function tests
# ---------------------------------------------------------------------------


def test_snapshot_file_not_found(tmp_path: pytest.TempPathFactory) -> None:
    """Returns a descriptive error message when the file does not exist."""
    missing = str(tmp_path / "nonexistent.py")
    result = create_tldr_snapshot(missing)
    assert result.startswith("Error:")
    assert "not found" in result


def test_snapshot_invalid_python(tmp_path: pytest.TempPathFactory) -> None:
    """Returns a parse-error message for syntactically invalid Python."""
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def oops(:\n", encoding="utf-8")
    result = create_tldr_snapshot(str(bad_file))
    assert result.startswith("Error parsing")
    assert "bad.py" in result


def test_snapshot_empty_file(tmp_path: pytest.TempPathFactory) -> None:
    """An empty file produces the header/footer but no L2/L4 sections."""
    empty = tmp_path / "empty.py"
    empty.write_text("", encoding="utf-8")
    result = create_tldr_snapshot(str(empty))
    assert "AST TLDR SNAPSHOT" in result
    assert "END SNAPSHOT" in result
    # No imports or globals for an empty file
    assert "[L2]" not in result
    assert "[L4]" not in result
    # Compression stats should report 0 original chars
    assert "Original Size: 0 chars" in result


def test_snapshot_imports_and_from_imports(tmp_path: pytest.TempPathFactory) -> None:
    """Both 'import X' and 'from X import Y' appear in the L2 section."""
    source = textwrap.dedent("""\
        import os
        import sys
        from pathlib import Path
        from typing import Any, Optional
    """)
    py = tmp_path / "imports.py"
    py.write_text(source, encoding="utf-8")

    result = create_tldr_snapshot(str(py))
    assert "[L2] DEPENDENCIES (Imports):" in result
    assert "  - os" in result
    assert "  - sys" in result
    assert "  - pathlib.Path" in result
    assert "  - typing.Any" in result
    assert "  - typing.Optional" in result


def test_snapshot_global_assignments(tmp_path: pytest.TempPathFactory) -> None:
    """Top-level variable assignments appear in L4."""
    source = textwrap.dedent("""\
        TIMEOUT = 30
        NAME = "agent"
    """)
    py = tmp_path / "globals.py"
    py.write_text(source, encoding="utf-8")

    result = create_tldr_snapshot(str(py))
    assert "[L4] GLOBAL STATE:" in result
    assert "  - TIMEOUT" in result
    assert "  - NAME" in result


def test_snapshot_functions_with_args_and_returns(
    tmp_path: pytest.TempPathFactory,
) -> None:
    """Functions show arguments, *args/**kwargs, return/yield markers, and docstrings."""
    source = textwrap.dedent("""\
        def greet(name, *args, **kwargs):
            \"\"\"Say hello.\"\"\"
            return f"hi {name}"

        def gen(n):
            yield n
    """)
    py = tmp_path / "funcs.py"
    py.write_text(source, encoding="utf-8")

    result = create_tldr_snapshot(str(py))
    # Signature includes args, vararg, kwarg
    assert "def greet(name, *args, **kwargs)" in result
    # Return marker
    assert "return" in result
    # Docstring extracted
    assert '"""Say hello...."""' in result
    # Generator has yield marker
    assert "def gen(n)" in result
    assert "yield" in result


def test_snapshot_class_with_methods(tmp_path: pytest.TempPathFactory) -> None:
    """Classes show signature, docstring, and nested methods with indentation."""
    source = textwrap.dedent("""\
        class Engine:
            \"\"\"Core engine.\"\"\"

            def start(self):
                return True

            def stop(self):
                pass
    """)
    py = tmp_path / "cls.py"
    py.write_text(source, encoding="utf-8")

    result = create_tldr_snapshot(str(py))
    assert 'class Engine:  """Core engine...."""' in result
    # Methods should be indented under the class
    assert "  def start(self)" in result
    assert "  def stop(self)" in result
    # start() returns, stop() does not
    assert "start(self) -> [return]" in result
    # stop has no return/yield, so no arrow
    lines = result.split("\n")
    stop_lines = [line for line in lines if "def stop" in line]
    assert len(stop_lines) == 1
    assert "->" not in stop_lines[0]


def test_snapshot_async_function(tmp_path: pytest.TempPathFactory) -> None:
    """Async functions are prefixed with 'async def'."""
    source = textwrap.dedent("""\
        async def fetch(url):
            return await something(url)
    """)
    py = tmp_path / "async_funcs.py"
    py.write_text(source, encoding="utf-8")

    result = create_tldr_snapshot(str(py))
    assert "async def fetch(url)" in result
    assert "return" in result


def test_snapshot_compression_footer(tmp_path: pytest.TempPathFactory) -> None:
    """Footer contains original size, TLDR size, and a non-negative compression %."""
    source = textwrap.dedent("""\
        import os
        GLOBAL = 42
        def func():
            return True
    """)
    py = tmp_path / "footer.py"
    py.write_text(source, encoding="utf-8")

    result = create_tldr_snapshot(str(py))
    assert "Original Size:" in result
    assert "TLDR Size:" in result
    assert "Compression:" in result
    assert "reduction" in result


# ---------------------------------------------------------------------------
# TLDRReadEnforcerTool — async tool wrapper tests
# ---------------------------------------------------------------------------


async def test_tool_metadata(tool: TLDRReadEnforcerTool) -> None:
    """Tool exposes correct name, description, and parameters_schema."""
    assert tool.name == "tldr_read_enforcer"
    assert "AST" in tool.description or "snapshot" in tool.description
    schema = tool.parameters_schema
    assert schema["required"] == ["file_path"]
    assert "file_path" in schema["properties"]


async def test_tool_execute_success(
    tool: TLDRReadEnforcerTool, context: ToolContext, tmp_path: pytest.TempPathFactory
) -> None:
    """Tool returns ToolResult.ok with snapshot content for a valid Python file."""
    py = tmp_path / "sample.py"
    py.write_text("def hello():\n    pass\n", encoding="utf-8")
    result = await tool.execute({"file_path": str(py)}, context)
    assert result.success is True
    assert "AST TLDR SNAPSHOT" in result.output
    assert "def hello()" in result.output


async def test_tool_execute_missing_param(
    tool: TLDRReadEnforcerTool, context: ToolContext
) -> None:
    """Tool returns failure when file_path is missing or empty."""
    result_empty = await tool.execute({}, context)
    assert result_empty.success is False
    assert "required" in result_empty.error.lower()

    result_blank = await tool.execute({"file_path": ""}, context)
    assert result_blank.success is False
    assert "required" in result_blank.error.lower()


async def test_tool_execute_nonexistent_file(
    tool: TLDRReadEnforcerTool, context: ToolContext, tmp_path: pytest.TempPathFactory
) -> None:
    """Tool returns ToolResult.ok (snapshot function handles errors internally)."""
    missing = str(tmp_path / "ghost.py")
    result = await tool.execute({"file_path": missing}, context)
    # create_tldr_snapshot returns an error string but doesn't raise,
    # so the tool wraps it in ToolResult.ok
    assert result.success is True
    assert "Error" in result.output
    assert "not found" in result.output
