"""File operations tool with path allowlist enforcement and traversal hardening."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent33.tools.base import ToolContext, ToolResult


class FileOpsTool:
    """Read, write, and list files within allowed paths."""

    @property
    def name(self) -> str:
        return "file_ops"

    @property
    def description(self) -> str:
        return "Read, write, or list files on the local filesystem."

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["read", "write", "list"],
                    "description": "File operation to perform.",
                },
                "path": {
                    "type": "string",
                    "description": "Target file or directory path.",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write (for 'write' operation).",
                    "default": "",
                },
            },
            "required": ["operation", "path"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Run a file operation.

        Parameters
        ----------
        params:
            operation : str  - One of 'read', 'write', 'list'.
            path      : str  - Target file or directory path.
            content   : str  - Content to write (for 'write' operation).
        """
        operation: str = params.get("operation", "").strip()
        raw_path: str = params.get("path", "").strip()

        if not operation:
            return ToolResult.fail("No operation specified (read, write, list)")
        if not raw_path:
            return ToolResult.fail("No path specified")

        # --- Path traversal hardening ---
        # Block null bytes (can bypass C-based path routines)
        if "\x00" in raw_path:
            return ToolResult.fail("Null bytes are not allowed in file paths")

        resolved = Path(raw_path).resolve()

        # Block symlinks that escape the allowlist
        if not self._path_allowed(resolved, context):
            return ToolResult.fail(
                f"Path '{resolved}' is outside the allowed directories: {context.path_allowlist}"
            )

        # If the target is a symlink, resolve and re-check
        if resolved.is_symlink():
            real_target = resolved.resolve(strict=False)
            if not self._path_allowed(real_target, context):
                return ToolResult.fail(
                    f"Symlink target '{real_target}' is outside the allowed directories"
                )

        if operation == "read":
            return await self._read(resolved)
        if operation == "write":
            content: str = params.get("content", "")
            return await self._write(resolved, content, context)
        if operation == "list":
            return await self._list(resolved)
        return ToolResult.fail(f"Unknown operation: {operation}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    async def _read(self, path: Path) -> ToolResult:
        try:
            text = path.read_text(encoding="utf-8")
            return ToolResult.ok(text)
        except FileNotFoundError:
            return ToolResult.fail(f"File not found: {path}")
        except OSError as exc:
            return ToolResult.fail(f"Read error: {exc}")

    async def _write(self, path: Path, content: str, context: ToolContext) -> ToolResult:
        try:
            # Verify parent directory is also within allowlist
            parent = path.parent.resolve()
            if not self._path_allowed(parent, context):
                return ToolResult.fail(
                    f"Parent directory '{parent}' is outside the allowed directories"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return ToolResult.ok(f"Wrote {len(content)} bytes to {path}")
        except OSError as exc:
            return ToolResult.fail(f"Write error: {exc}")

    async def _list(self, path: Path) -> ToolResult:
        try:
            if path.is_file():
                stat = path.stat()
                return ToolResult.ok(
                    f"{path.name}  ({stat.st_size} bytes, modified {stat.st_mtime})"
                )
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
            lines = []
            for entry in entries:
                kind = "dir" if entry.is_dir() else "file"
                lines.append(f"{kind}  {entry.name}")
            return ToolResult.ok("\n".join(lines) if lines else "(empty directory)")
        except FileNotFoundError:
            return ToolResult.fail(f"Path not found: {path}")
        except OSError as exc:
            return ToolResult.fail(f"List error: {exc}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _path_allowed(resolved: Path, context: ToolContext) -> bool:
        """Check that *resolved* falls within one of the allowed paths.

        Uses Path containment checks that are resilient to ``..`` traversal.
        """
        if not context.path_allowlist:
            return True
        for allowed in context.path_allowlist:
            allowed_resolved = Path(allowed).resolve()
            try:
                resolved.relative_to(allowed_resolved)
                return True
            except ValueError:
                continue
        return False
