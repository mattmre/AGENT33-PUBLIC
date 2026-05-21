import ast
import os
import traceback
from typing import Any

from agent33.tools.base import Tool, ToolContext, ToolResult


def create_tldr_snapshot(file_path: str) -> str:
    """
    Reads a Python file and returns a 5-layer AST semantic snapshot instead of raw lines.
    L1: Class and Function signatures
    L2: Imports (Dependencies)
    L3: Docstrings
    L4: Global Assignments
    L5: Returns/Yields
    """
    if not os.path.exists(file_path):
        return f"Error: File {file_path} not found."

    try:
        with open(file_path, encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source)
    except Exception as e:
        return f"Error parsing ATS for {file_path}: {str(e)}"

    output = []
    output.append(f"--- AST TLDR SNAPSHOT: {file_path} ---")

    # L2: Imports
    imports = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                imports.append(f"{node.module}.{alias.name}")
    if imports:
        output.append("\n[L2] DEPENDENCIES (Imports):")
        for imp in imports:
            output.append(f"  - {imp}")

    # L4: Global Assignments
    globals_list = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    globals_list.append(target.id)
    if globals_list:
        output.append("\n[L4] GLOBAL STATE:")
        for g in globals_list:
            output.append(f"  - {g}")

    # L1, L3, L5: Signatures, Docstrings, and Returns
    output.append("\n[L1/L3/L5] STRUCTURE & SEMANTICS:")

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.lines: list[str] = []
            self.indent: int = 0

        def get_indent(self) -> str:
            return "  " * self.indent

        def extract_returns(self, node: ast.AST) -> list[str]:
            returns: list[str] = []
            for child in ast.walk(node):
                if isinstance(child, ast.Return):
                    returns.append("return")
                elif isinstance(child, ast.Yield):
                    returns.append("yield")
            return list(set(returns))

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            doc = ast.get_docstring(node)
            doc_str = f'  """{doc.split(chr(10))[0]}..."""' if doc else ""
            self.lines.append(f"{self.get_indent()}class {node.name}:{doc_str}")

            self.indent += 1
            self.generic_visit(node)
            self.indent -= 1

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._handle_func(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._handle_func(node, is_async=True)

        def _handle_func(
            self,
            node: ast.FunctionDef | ast.AsyncFunctionDef,
            is_async: bool = False,
        ) -> None:
            doc = ast.get_docstring(node)
            doc_str = f'  """{doc.split(chr(10))[0]}..."""' if doc else ""

            # Extract arguments
            args = [a.arg for a in node.args.args]
            if node.args.vararg:
                args.append(f"*{node.args.vararg.arg}")
            if node.args.kwarg:
                args.append(f"**{node.args.kwarg.arg}")
            arg_str = ", ".join(args)

            # Extract Returns
            ret_types = self.extract_returns(node)
            ret_str = f" -> [{','.join(ret_types)}]" if ret_types else ""

            prefix = "async def" if is_async else "def"
            self.lines.append(
                f"{self.get_indent()}{prefix} {node.name}({arg_str}){ret_str}:{doc_str}"
            )

            self.indent += 1
            self.generic_visit(node)
            self.indent -= 1

    v = Visitor()
    v.visit(tree)
    output.extend(v.lines)

    # Add token warnings
    summary = "\n".join(output)

    footer = [
        "\n--- END SNAPSHOT ---",
        f"Original Size: {len(source)} chars",
        f"TLDR Size: {len(summary)} chars",
        f"Compression: {100 - (len(summary) / max(1, len(source)) * 100):.1f}% reduction",
    ]

    return summary + "\n".join(footer)


class TLDRReadEnforcerTool(Tool):
    """Compressed 5-layer AST semantic snapshot reader.

    Reads a Python file and returns a highly compressed AST snapshot
    instead of raw tokens. Use INSTEAD of cat or view_file when trying
    to understand file architecture, preventing context window bloat.
    """

    name = "tldr_read_enforcer"
    description = (
        "Reads a Python file and returns a 5-layer AST semantic"
        " snapshot (Signatures, Imports, Docstrings, Globals,"
        " Returns) instead of raw text, saving 95% of tokens."
        " Use this to understand file architecture."
    )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The absolute path to the Python file to analyze",
                }
            },
            "required": ["file_path"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        file_path = params.get("file_path", "")
        if not file_path:
            return ToolResult.fail("file_path parameter is required.")

        try:
            snapshot = create_tldr_snapshot(file_path)
            return ToolResult.ok(snapshot)
        except Exception as e:
            return ToolResult.fail(
                f"Failed to generate TLDR snapshot: {str(e)}\n{traceback.format_exc()}"
            )


if __name__ == "__main__":
    # Quick test if run directly
    import sys

    if len(sys.argv) > 1:
        print(create_tldr_snapshot(sys.argv[1]))
    else:
        print("Usage: python tldr_enforcer.py <file_path>")
