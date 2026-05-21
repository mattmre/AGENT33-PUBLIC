"""Governed patch application tool with workspace containment."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.mutation_audit import (
    MutationAuditFileRecord,
    MutationAuditRecord,
    MutationAuditStore,
)


class PatchError(ValueError):
    """Raised when a patch payload is invalid or unsafe."""


@dataclasses.dataclass(frozen=True, slots=True)
class PatchBlock:
    """Single update block inside an ``Update File`` hunk."""

    lines: tuple[tuple[str, str], ...]


@dataclasses.dataclass(frozen=True, slots=True)
class PatchChange:
    """Parsed change operation for one file path."""

    action: str
    path: str
    new_path: str | None = None
    add_lines: tuple[str, ...] = ()
    blocks: tuple[PatchBlock, ...] = ()


@dataclasses.dataclass(frozen=True, slots=True)
class PlannedChange:
    """Resolved change ready for preview or execution."""

    action: str
    source_path: Path
    target_path: Path
    before_content: str | None
    after_content: str | None
    added_lines: int
    removed_lines: int


class ApplyPatchTool:
    """Apply OpenAI/Codex-style patch payloads within an allowed workspace."""

    def __init__(self, audit_store: MutationAuditStore | None = None) -> None:
        self._audit_store = audit_store or MutationAuditStore()

    @property
    def name(self) -> str:
        return "apply_patch"

    @property
    def description(self) -> str:
        return "Apply a structured patch to files inside the allowed workspace."

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "Patch text using the *** Begin Patch format.",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview the mutation without writing files.",
                    "default": False,
                },
            },
            "required": ["patch"],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Preview or apply a structured patch."""
        dry_run = bool(params.get("dry_run", False))
        patch_text = str(params.get("patch", ""))
        approval_id = str(params.get("__approval_id", ""))
        if not patch_text.strip():
            return self._record_failure(
                context=context,
                dry_run=dry_run,
                approval_id=approval_id,
                error="Patch payload is required",
            )

        try:
            changes = self._parse_patch(patch_text)
            plans = [self._plan_change(change, context) for change in changes]
            if not dry_run:
                for plan in plans:
                    self._apply_change(plan)
            status = "preview" if dry_run else "applied"
            record = MutationAuditRecord(
                requested_by=context.requested_by,
                tenant_id=context.tenant_id,
                dry_run=dry_run,
                status=status,
                success=True,
                summary=f"{status.title()}ed {len(plans)} patch operation(s).",
                approval_id=approval_id,
                files=[self._build_audit_file(plan) for plan in plans],
            )
            recorded = self._audit_store.record(record)
            return ToolResult.ok(
                json.dumps(
                    {
                        "mutation_id": recorded.mutation_id,
                        "dry_run": dry_run,
                        "status": status,
                        "operations": [self._build_operation_summary(plan) for plan in plans],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        except PatchError as exc:
            return self._record_failure(
                context=context,
                dry_run=dry_run,
                approval_id=approval_id,
                error=str(exc),
            )

    def _record_failure(
        self,
        *,
        context: ToolContext,
        dry_run: bool,
        approval_id: str,
        error: str,
    ) -> ToolResult:
        self._audit_store.record(
            MutationAuditRecord(
                requested_by=context.requested_by,
                tenant_id=context.tenant_id,
                dry_run=dry_run,
                status="failed",
                success=False,
                summary="Patch execution failed.",
                error=error,
                approval_id=approval_id,
            )
        )
        return ToolResult.fail(error)

    def _plan_change(self, change: PatchChange, context: ToolContext) -> PlannedChange:
        source_path = self._resolve_path(change.path, context)
        target_path = (
            self._resolve_path(change.new_path, context) if change.new_path else source_path
        )
        if change.action == "add":
            if source_path.exists():
                raise PatchError(f"Cannot add file that already exists: {source_path}")
            after_content = "\n".join(change.add_lines)
            return PlannedChange(
                action="add",
                source_path=source_path,
                target_path=target_path,
                before_content=None,
                after_content=after_content,
                added_lines=len(change.add_lines),
                removed_lines=0,
            )
        if change.action == "delete":
            before_content = self._read_file(source_path)
            return PlannedChange(
                action="delete",
                source_path=source_path,
                target_path=target_path,
                before_content=before_content,
                after_content=None,
                added_lines=0,
                removed_lines=len(before_content.splitlines()),
            )
        before_content = self._read_file(source_path)
        after_content, added_lines, removed_lines = self._apply_blocks(
            before_content,
            change.blocks,
        )
        if source_path != target_path and target_path.exists():
            raise PatchError(f"Cannot move file onto existing path: {target_path}")
        return PlannedChange(
            action="update",
            source_path=source_path,
            target_path=target_path,
            before_content=before_content,
            after_content=after_content,
            added_lines=added_lines,
            removed_lines=removed_lines,
        )

    def _apply_change(self, plan: PlannedChange) -> None:
        if plan.action == "add":
            assert plan.after_content is not None
            plan.target_path.parent.mkdir(parents=True, exist_ok=True)
            plan.target_path.write_text(plan.after_content, encoding="utf-8")
            return
        if plan.action == "delete":
            plan.source_path.unlink()
            return
        assert plan.after_content is not None
        plan.target_path.parent.mkdir(parents=True, exist_ok=True)
        plan.target_path.write_text(plan.after_content, encoding="utf-8")
        if plan.source_path != plan.target_path and plan.source_path.exists():
            plan.source_path.unlink()

    def _apply_blocks(
        self,
        before_content: str,
        blocks: tuple[PatchBlock, ...],
    ) -> tuple[str, int, int]:
        original_lines = before_content.splitlines()
        trailing_newline = before_content.endswith("\n")
        cursor = 0
        result_lines: list[str] = []
        added_lines = 0
        removed_lines = 0

        for block in blocks:
            old_lines = [text for prefix, text in block.lines if prefix != "+"]
            new_lines = [text for prefix, text in block.lines if prefix != "-"]
            added_lines += sum(1 for prefix, _ in block.lines if prefix == "+")
            removed_lines += sum(1 for prefix, _ in block.lines if prefix == "-")
            start = self._find_block_start(original_lines, old_lines, cursor)
            if start is None:
                raise PatchError("Patch context did not match the current file contents")
            result_lines.extend(original_lines[cursor:start])
            result_lines.extend(new_lines)
            cursor = start + len(old_lines)

        result_lines.extend(original_lines[cursor:])
        after_content = "\n".join(result_lines)
        if trailing_newline and result_lines:
            after_content += "\n"
        return after_content, added_lines, removed_lines

    @staticmethod
    def _find_block_start(
        source_lines: list[str],
        old_lines: list[str],
        cursor: int,
    ) -> int | None:
        if not old_lines:
            return cursor
        limit = len(source_lines) - len(old_lines) + 1
        for index in range(max(cursor, 0), max(limit, 0)):
            if source_lines[index : index + len(old_lines)] == old_lines:
                return index
        if len(old_lines) == 0 and cursor <= len(source_lines):
            return cursor
        return None

    def _resolve_path(self, raw_path: str | None, context: ToolContext) -> Path:
        if not raw_path:
            raise PatchError("Patch file path is required")
        candidate = Path(raw_path)
        if "\x00" in raw_path:
            raise PatchError("Null bytes are not allowed in patch paths")
        base_dir = context.working_dir.resolve()
        resolved = (
            (base_dir / candidate).resolve(strict=False)
            if not candidate.is_absolute()
            else candidate.resolve(strict=False)
        )
        roots = [Path(item).resolve() for item in context.path_allowlist] or [base_dir]
        if not any(self._is_within_root(resolved, root) for root in roots):
            raise PatchError(f"Patch path escapes the allowed workspace: {raw_path}")
        return resolved

    @staticmethod
    def _is_within_root(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _read_file(path: Path) -> str:
        if not path.exists():
            raise PatchError(f"Target file does not exist: {path}")
        if path.is_dir():
            raise PatchError(f"Patch target must be a file, not a directory: {path}")
        return path.read_text(encoding="utf-8")

    def _build_audit_file(self, plan: PlannedChange) -> MutationAuditFileRecord:
        return MutationAuditFileRecord(
            action=plan.action,
            path=str(plan.source_path),
            new_path="" if plan.source_path == plan.target_path else str(plan.target_path),
            added_lines=plan.added_lines,
            removed_lines=plan.removed_lines,
            before_sha256=self._hash_content(plan.before_content),
            after_sha256=self._hash_content(plan.after_content),
        )

    def _build_operation_summary(self, plan: PlannedChange) -> dict[str, Any]:
        return {
            "action": plan.action,
            "path": str(plan.source_path),
            "new_path": "" if plan.source_path == plan.target_path else str(plan.target_path),
            "added_lines": plan.added_lines,
            "removed_lines": plan.removed_lines,
        }

    @staticmethod
    def _hash_content(content: str | None) -> str:
        if content is None:
            return ""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _parse_patch(self, patch_text: str) -> list[PatchChange]:
        lines = patch_text.splitlines()
        if not lines or lines[0] != "*** Begin Patch":
            raise PatchError("Patch must start with '*** Begin Patch'")
        if lines[-1] != "*** End Patch":
            raise PatchError("Patch must end with '*** End Patch'")

        changes: list[PatchChange] = []
        index = 1
        while index < len(lines) - 1:
            header = lines[index]
            if header.startswith("*** Add File: "):
                path = header.removeprefix("*** Add File: ").strip()
                index += 1
                add_lines: list[str] = []
                while index < len(lines) - 1 and not lines[index].startswith("*** "):
                    line = lines[index]
                    if not line.startswith("+"):
                        raise PatchError("Add File hunks may only contain '+' lines")
                    add_lines.append(line[1:])
                    index += 1
                changes.append(PatchChange(action="add", path=path, add_lines=tuple(add_lines)))
                continue
            if header.startswith("*** Delete File: "):
                path = header.removeprefix("*** Delete File: ").strip()
                index += 1
                changes.append(PatchChange(action="delete", path=path))
                continue
            if header.startswith("*** Update File: "):
                path = header.removeprefix("*** Update File: ").strip()
                index += 1
                new_path: str | None = None
                if index < len(lines) - 1 and lines[index].startswith("*** Move to: "):
                    new_path = lines[index].removeprefix("*** Move to: ").strip()
                    index += 1
                raw_block_lines: list[str] = []
                while index < len(lines) - 1 and not lines[index].startswith("*** "):
                    raw_block_lines.append(lines[index])
                    index += 1
                changes.append(
                    PatchChange(
                        action="update",
                        path=path,
                        new_path=new_path,
                        blocks=self._parse_update_blocks(raw_block_lines),
                    )
                )
                continue
            raise PatchError(f"Unsupported patch header: {header}")

        if not changes:
            raise PatchError("Patch did not contain any file changes")
        return changes

    def _parse_update_blocks(self, raw_lines: list[str]) -> tuple[PatchBlock, ...]:
        blocks: list[PatchBlock] = []
        current: list[tuple[str, str]] = []
        for line in raw_lines:
            if line.startswith("@@"):
                if current:
                    blocks.append(PatchBlock(lines=tuple(current)))
                    current = []
                continue
            if line == "*** End of File":
                continue
            if not line:
                raise PatchError("Update File lines must start with ' ', '+', '-', or '@@'")
            prefix = line[0]
            if prefix not in {" ", "+", "-"}:
                raise PatchError("Update File lines must start with ' ', '+', '-', or '@@'")
            current.append((prefix, line[1:]))
        if current:
            blocks.append(PatchBlock(lines=tuple(current)))
        return tuple(blocks)
